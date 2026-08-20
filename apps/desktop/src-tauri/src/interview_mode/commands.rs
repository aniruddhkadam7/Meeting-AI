//! Tauri commands for Interview Mode: overlay window lifecycle + the
//! ASK AI flow (optional local RAG -> backend -> LLM -> streamed answer).
//!
//! Retrieval's top_k/similarity_threshold/max_context_chars/timeout are all
//! hardware-tier-driven (`hardware::PerformanceManager::effective_config`)
//! rather than hardcoded here — see `hardware::manager` for the tier table
//! and docs/performance-tuning.md for the benchmark evidence behind it.

use tauri::{AppHandle, Emitter, State};

use crate::backend::{AskRequest, AskRetrievedChunk, BackendClient, ConversationTurn};
use crate::rag::{RagClient, RetrievalPlanner};
use crate::state::AppState;

use super::window::{self, OverlayCaptureStatus};

/// Answer-shaping options chosen in the overlay's settings panel. Everything
/// is optional: `Default` reproduces the plain "natural, default length"
/// behavior, so a caller that supplies nothing still gets a good answer.
#[derive(Debug, Clone, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct AskOptions {
    #[serde(default = "default_answer_length")]
    pub answer_length: String,
    #[serde(default = "default_response_style")]
    pub response_style: String,
    #[serde(default)]
    pub role: Option<String>,
    #[serde(default)]
    pub job_description: Option<String>,
    #[serde(default = "default_english_level")]
    pub english_level: String,
    #[serde(default = "default_humanization")]
    pub humanization: String,
}

fn default_answer_length() -> String {
    "default".to_string()
}

fn default_response_style() -> String {
    "natural".to_string()
}

fn default_english_level() -> String {
    "simple".to_string()
}

fn default_humanization() -> String {
    "natural".to_string()
}

/// One prior exchange in this Interview Mode session, as sent by the overlay.
#[derive(Debug, Clone, serde::Deserialize)]
pub struct PriorTurn {
    pub question: String,
    pub answer: String,
}

/// How many prior turns to forward. The overlay keeps the whole conversation
/// on screen, but only the recent tail is worth paying for in the prompt:
/// every turn adds tokens to time-to-first-token, which is the number the user
/// feels mid-interview. Six turns comfortably covers "why did you choose
/// that?" style follow-ups, which almost always refer to the last exchange or
/// two.
const MAX_HISTORY_TURNS: usize = 6;

impl Default for AskOptions {
    fn default() -> Self {
        Self {
            answer_length: default_answer_length(),
            response_style: default_response_style(),
            role: None,
            job_description: None,
            english_level: default_english_level(),
            humanization: default_humanization(),
        }
    }
}

// Window creation/show/hide on Windows must happen on the same OS thread that
// owns the window message loop (the main thread). Tauri dispatches
// non-async `#[tauri::command]`s onto its blocking thread pool, NOT the main
// thread, so calling WebviewWindowBuilder::build()/show()/hide() directly
// from here deadlocks: the worker thread blocks waiting for the main-thread
// window/message APIs, while the main thread is itself waiting on IPC. Route
// the actual window work through `run_on_main_thread` and use a channel to
// bring the result back to the (async) command so the IPC call still
// completes normally instead of hanging forever.
#[tauri::command]
pub async fn show_interview_overlay(app: AppHandle) -> Result<OverlayCaptureStatus, String> {
    run_on_main(&app, window::show_overlay_window).await
}

#[tauri::command]
pub async fn hide_interview_overlay(app: AppHandle) -> Result<(), String> {
    run_on_main(&app, window::close_overlay_window).await
}

#[tauri::command]
pub async fn toggle_interview_overlay(app: AppHandle) -> Result<OverlayCaptureStatus, String> {
    run_on_main(&app, window::toggle_overlay_window).await
}

/// Applied immediately when the user flips "Always on top" in the overlay's
/// Settings panel — see `overlaySettings.ts`/`OverlaySettingsPanel.tsx`.
#[tauri::command]
pub async fn set_overlay_always_on_top(app: AppHandle, enabled: bool) -> Result<(), String> {
    run_on_main(&app, move |app| window::set_overlay_always_on_top(app, enabled)).await
}

/// Applied when the user changes "Overlay size" in Settings. `fraction` is
/// the side length as a fraction of the primary monitor's shorter dimension
/// (small=0.45, medium=0.6, large=0.75 — chosen client-side).
#[tauri::command]
pub async fn resize_interview_overlay(app: AppHandle, fraction: f64) -> Result<(), String> {
    run_on_main(&app, move |app| window::resize_overlay(app, fraction)).await
}

async fn run_on_main<T, F>(app: &AppHandle, f: F) -> Result<T, String>
where
    T: Send + 'static,
    F: FnOnce(&AppHandle) -> Result<T, String> + Send + 'static,
{
    let (tx, rx) = std::sync::mpsc::channel();
    let app_for_main = app.clone();
    app.run_on_main_thread(move || {
        let result = f(&app_for_main);
        let _ = tx.send(result);
    })
    .map_err(|e| format!("failed to schedule work on main thread: {e}"))?;

    tauri::async_runtime::spawn_blocking(move || {
        rx.recv()
            .map_err(|e| format!("main-thread task did not respond: {e}"))?
    })
    .await
    .map_err(|e| format!("main-thread task panicked: {e}"))?
}

/// Fetches the full extracted text of the most recently uploaded document of
/// `document_type` (RESUME or JOB_DESCRIPTION), bypassing RAG chunk search
/// entirely. CV and job description are short enough to just read in full —
/// unlike the "Upload documents" catch-all, there is no size reason to chunk
/// and similarity-search them, and doing so only adds a race (the document
/// may not have finished indexing yet) and a chance of missing/skipping
/// content that full-text inclusion can't have. Returns `None` on any
/// failure (RAG unavailable, no matching document, still extracting) —
/// exactly like `retrieval_could_help`'s failures, this must never fail the
/// ask itself, only mean the answer proceeds without that document.
async fn fetch_document_full_text(document_type: &str) -> Option<String> {
    let client = RagClient::new();
    let documents = client.list_documents(None).await.ok()?;
    let latest = documents
        .into_iter()
        .filter(|d| d.document_type == document_type && d.status == "READY")
        .max_by(|a, b| a.updated_at.total_cmp(&b.updated_at))?;
    client.get_document_text(&latest.document_id).await.ok().flatten()
}

/// Runs the ASK AI flow for a single question:
///
///     question -> (retrieval, only when it could help) -> ONE LLM call -> stream
///
/// Retrieval is skipped entirely for questions that are plainly about a
/// concept rather than the candidate ("What is Kubernetes?"), since searching
/// a personal CV for those can only ever return noise while costing latency
/// the user feels. When retrieval does run and returns nothing useful, the
/// request proceeds with an empty `retrieved_context` — the backend answers
/// from general knowledge. Retrieval failure is never an error here.
///
/// The uploaded CV and job description, if any, are fetched as full text
/// (see `fetch_document_full_text`) and sent unconditionally on every
/// question — not gated behind `retrieval_could_help`, since reading a
/// one-page document costs nothing worth gating. `retrieved_context` (RAG)
/// still covers the general "Upload documents" catch-all category only.
///
/// Streams back as `interview-mode:answer-delta` events, finishing with
/// `interview-mode:answer-complete`. Only ever invoked by the frontend in
/// direct response to ASK AI / ENTER — never automatically.
#[tauri::command]
pub async fn ask_interview_question(
    app: AppHandle,
    _state: State<'_, AppState>,
    question: String,
    options: Option<AskOptions>,
    history: Option<Vec<PriorTurn>>,
) -> Result<String, String> {
    use crate::hardware::telemetry::{finish, PipelineStage, Stopwatch};

    let question_to_answer = Stopwatch::start();

    let trimmed = question.trim();
    if trimmed.is_empty() {
        return Err("no question text to send".into());
    }
    let options = options.unwrap_or_default();

    let history = trim_history(history.unwrap_or_default());

    // CV and job description are fetched as full text unconditionally (see
    // `fetch_document_full_text`), regardless of `retrieval_could_help` —
    // unlike chunk search, reading a one-page document has no latency cost
    // worth gating. Deferred to just before use below, after retrieval, so
    // the (optional, possibly slower) RAG search isn't held up behind them.
    let resume_fetch = fetch_document_full_text("RESUME");
    let job_description_fetch = fetch_document_full_text("JOB_DESCRIPTION");

    let retrieved = if retrieval_could_help(trimmed) {
        // `_checked`: retrieval is asked once per question, so this is the
        // natural per-question checkpoint for the memory-pressure tracker.
        // The tracker's own hysteresis (2 consecutive low samples to enter
        // pressure, 90s sustained recovery to exit) means being checked
        // this often does not translate into frequent config changes.
        let cfg = crate::hardware::effective_config_checked(&app);
        let planner = RetrievalPlanner::new()
            .with_config(cfg.rag_top_k, cfg.rag_similarity_threshold, cfg.rag_max_context_chars)
            .with_timeout(std::time::Duration::from_millis(cfg.rag_retrieval_timeout_ms));
        let retrieval_timer = Stopwatch::start();
        let results = planner.plan_for_question(trimmed).await;
        finish(retrieval_timer, PipelineStage::RagRetrieval, &crate::hardware::perf_context(&app));
        results
    } else {
        log::debug!("Interview Mode: skipping retrieval for conceptual question");
        Vec::new()
    };

    let resume_text = resume_fetch.await;
    let uploaded_job_description = job_description_fetch.await;

    let request = AskRequest {
        question: trimmed.to_string(),
        conversation_history: history,
        // RESUME/JOB_DESCRIPTION are excluded here — they're already sent in
        // full via candidate_context/job_description below, so including
        // RAG chunks of the same documents too would just duplicate content
        // and risk the model treating a partial chunk as the whole picture.
        // "Upload documents" (the general catch-all) still comes through
        // here, since it's the case retrieval actually exists for.
        retrieved_context: retrieved
            .into_iter()
            .filter(|r| r.metadata.document_type != "RESUME" && r.metadata.document_type != "JOB_DESCRIPTION")
            .map(|r| AskRetrievedChunk {
                text: r.text,
                source_filename: r.metadata.filename,
                document_type: r.metadata.document_type,
                score: r.score,
            })
            .collect(),
        candidate_context: resume_text,
        role: options.role,
        // The uploaded document's full text (when present) is more complete
        // than the settings panel's manually typed/pasted job_description
        // field, so it takes priority; the typed field remains the fallback
        // for users who never uploaded a JD file at all.
        job_description: uploaded_job_description.or(options.job_description),
        answer_length: options.answer_length,
        response_style: options.response_style,
        english_level: options.english_level,
        humanization: options.humanization,
    };

    let client = BackendClient::new();
    let app_for_events = app.clone();
    let llm_timer = Stopwatch::start();
    let first_token = crate::hardware::telemetry::FirstTokenTracker::new();
    let first_token_recorder = first_token.recorder();
    let answer = client
        .ask_stream(&request, move |delta| {
            first_token_recorder.mark();
            let _ = app_for_events.emit("interview-mode:answer-delta", delta);
        })
        .await?;

    let ctx = crate::hardware::perf_context(&app);
    if let Some(ms) = first_token.elapsed_ms() {
        crate::hardware::telemetry::log_stage_ms(PipelineStage::LlmFirstToken, ms, &ctx);
    }
    finish(llm_timer, PipelineStage::LlmTotal, &ctx);
    finish(question_to_answer, PipelineStage::QuestionToAnswer, &ctx);

    let _ = app.emit("interview-mode:answer-complete", &answer);
    Ok(answer)
}

/// Normalizes the overlay's conversation history into what the backend wants:
/// the most recent complete turns, still oldest-first.
///
/// Incomplete turns are dropped rather than sent as empty strings — the
/// backend schema requires non-empty text on both sides, so a turn whose
/// answer failed or is still streaming would be rejected and take the whole
/// request down with it.
fn trim_history(turns: Vec<PriorTurn>) -> Vec<ConversationTurn> {
    let mut history: Vec<ConversationTurn> = turns
        .into_iter()
        .filter(|t| !t.question.trim().is_empty() && !t.answer.trim().is_empty())
        .map(|t| ConversationTurn {
            question: t.question.trim().to_string(),
            answer: t.answer.trim().to_string(),
        })
        .collect();
    if history.len() > MAX_HISTORY_TURNS {
        history.drain(..history.len() - MAX_HISTORY_TURNS);
    }
    history
}

/// Whether searching the candidate's own documents could plausibly improve
/// this answer.
///
/// Biased towards retrieving: a false positive costs one fast local search
/// whose empty/irrelevant result is harmless, while a false negative loses
/// real personalization. Only questions that are unambiguously about a
/// concept — a definitional opener with no second-person reference anywhere —
/// skip it.
fn retrieval_could_help(question: &str) -> bool {
    let lowered = question.to_lowercase();

    // Any reference to the candidate makes this potentially personal,
    // whatever else the question looks like ("What is your experience with
    // Kubernetes?" opens definitionally but is entirely about them).
    const PERSONAL_MARKERS: [&str; 12] = [
        "your ",
        "you ",
        "you'",
        "yourself",
        "have you",
        "did you",
        "tell me about a time",
        "walk me through",
        "worked on",
        "experience with",
        "your experience",
        "a project where",
    ];
    if PERSONAL_MARKERS.iter().any(|m| lowered.contains(m)) {
        return true;
    }

    // Purely definitional openers with no personal reference: general
    // knowledge answers these completely, and the CV cannot contribute.
    const CONCEPTUAL_OPENERS: [&str; 12] = [
        "what is",
        "what are",
        "what's",
        "explain",
        "define",
        "how does",
        "how do",
        "how would",
        "why is",
        "why do",
        "difference between",
        "when should",
    ];
    let opener = lowered.trim_start_matches(|c: char| !c.is_alphanumeric());
    if CONCEPTUAL_OPENERS.iter().any(|o| opener.starts_with(o)) {
        return false;
    }

    true
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn conceptual_questions_skip_retrieval() {
        assert!(!retrieval_could_help("What is RAG?"));
        assert!(!retrieval_could_help("What is Kubernetes?"));
        assert!(!retrieval_could_help("Explain how TCP handles congestion."));
        assert!(!retrieval_could_help("What's the difference between a process and a thread?"));
        assert!(!retrieval_could_help("How does garbage collection work?"));
    }

    #[test]
    fn questions_about_the_candidate_retrieve() {
        assert!(retrieval_could_help("Tell me about your experience with Python."));
        assert!(retrieval_could_help("Have you worked with RAG?"));
        assert!(retrieval_could_help("Walk me through a project you're proud of."));
        assert!(retrieval_could_help("Tell me about a time you disagreed with a teammate."));
    }

    #[test]
    fn a_personal_reference_beats_a_definitional_opener() {
        // Opens like a concept question but is entirely about them — the
        // personal check must win, or "What is your experience with X?" would
        // lose its personalization.
        assert!(retrieval_could_help("What is your experience with Kubernetes?"));
        assert!(retrieval_could_help("How would you describe your testing approach?"));
    }

    #[test]
    fn unclassifiable_questions_default_to_retrieving() {
        // Biased towards retrieval: an irrelevant result is dropped by the
        // similarity threshold anyway, a missed one loses personalization.
        assert!(retrieval_could_help("Tell me about yourself."));
        assert!(retrieval_could_help("Kubernetes."));
    }

    fn turn(q: &str, a: &str) -> PriorTurn {
        PriorTurn {
            question: q.to_string(),
            answer: a.to_string(),
        }
    }

    #[test]
    fn history_keeps_the_most_recent_turns_oldest_first() {
        let turns: Vec<PriorTurn> = (0..MAX_HISTORY_TURNS + 3)
            .map(|i| turn(&format!("q{i}"), &format!("a{i}")))
            .collect();
        let trimmed = trim_history(turns);

        assert_eq!(trimmed.len(), MAX_HISTORY_TURNS);
        // The oldest turns are the ones dropped, and order is preserved.
        assert_eq!(trimmed.first().unwrap().question, "q3");
        assert_eq!(trimmed.last().unwrap().question, format!("q{}", MAX_HISTORY_TURNS + 2));
    }

    #[test]
    fn history_drops_incomplete_turns() {
        // A turn still streaming, or one whose request failed, has no answer.
        // Sending it would fail the backend's min_length validation and take
        // the whole follow-up down with it.
        let trimmed = trim_history(vec![
            turn("answered", "yes"),
            turn("still streaming", ""),
            turn("", "orphan answer"),
            turn("  ", "   "),
        ]);
        assert_eq!(trimmed.len(), 1);
        assert_eq!(trimmed[0].question, "answered");
    }

    #[test]
    fn history_is_trimmed_of_whitespace() {
        let trimmed = trim_history(vec![turn("  why?  ", "  because.  ")]);
        assert_eq!(trimmed[0].question, "why?");
        assert_eq!(trimmed[0].answer, "because.");
    }

    #[test]
    fn empty_history_is_fine() {
        assert!(trim_history(Vec::new()).is_empty());
    }

    #[test]
    fn ask_options_default_to_natural_default_length() {
        let options = AskOptions::default();
        assert_eq!(options.answer_length, "default");
        assert_eq!(options.response_style, "natural");
        assert!(options.role.is_none());
    }

    #[test]
    fn ask_options_deserialize_from_partial_frontend_payload() {
        let options: AskOptions = serde_json::from_str(r#"{"answerLength":"brief"}"#).unwrap();
        assert_eq!(options.answer_length, "brief");
        assert_eq!(options.response_style, "natural");
    }
}
