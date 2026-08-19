use std::io::Write;

use tauri::{Emitter, Manager, State};

use crate::audio::{
    AudioDeviceInfo, AudioDeviceManager, AudioSource, PauseSignal, StopSignal, SystemAudioCapture,
};
use crate::backend::{BackendClient, InterviewAnalysisRequest, SetupAnalysisRequest, SetupAnalysisResponse};
use crate::rag::{DocumentMetadata, KnowledgeBaseStatus, RagClient, SearchResponse};
use crate::state::AppState;
use crate::stt::SttSidecar;
use crate::transcript::{InterviewSession, RecordingState, TranscriptSegment};

#[derive(Clone, serde::Serialize)]
struct AudioLevelEvent {
    source: AudioSource,
    rms_level: f32,
}

#[derive(Clone, serde::Serialize)]
struct RecordingStateEvent {
    state: RecordingState,
}

#[tauri::command]
pub fn list_output_devices() -> Result<Vec<AudioDeviceInfo>, String> {
    AudioDeviceManager::list_output_devices()
}

#[tauri::command]
pub fn list_input_devices() -> Result<Vec<AudioDeviceInfo>, String> {
    AudioDeviceManager::list_input_devices()
}

/// Starts the full local pipeline: WASAPI system-audio capture -> PocketSphinx
/// sidecar -> TranscriptManager -> `transcript:update` / `audio:level` events to
/// the frontend. No network call happens here; the backend is only contacted later
/// when the user explicitly clicks "Analyze Interview" (see docs/architecture.md).
#[tauri::command]
pub fn start_system_audio_capture(
    app: tauri::AppHandle,
    state: State<'_, AppState>,
) -> Result<(), String> {
    log::info!("start_system_audio_capture: invoked");
    let mut session = state.capture.lock().map_err(|e| e.to_string())?;
    if session.stop_signal.is_some() {
        return Err("capture already running".into());
    }

    {
        let mut transcript = state.transcript.lock().map_err(|e| e.to_string())?;
        transcript.clear();
    }

    let (audio_tx, audio_rx) = crossbeam_channel::unbounded();
    let (stt_tx, stt_rx) = std::sync::mpsc::channel();
    let stop = StopSignal::new();
    let pause = PauseSignal::new();

    let session_start = crate::hardware::telemetry::Stopwatch::start();
    let audio_thread = SystemAudioCapture::start(audio_tx, stop.clone())?;

    // `_checked`: this is a natural checkpoint (recording session start) —
    // feeds a fresh RAM reading into the sustained-pressure tracker, which
    // may clamp `stt_num_threads` down if the machine has been under
    // memory pressure across the last couple of checkpoints (see
    // hardware::pressure). Any resulting downgrade/restoration is logged
    // from within effective_config_checked itself.
    let stt_num_threads = crate::hardware::effective_config_checked(&app).stt_num_threads;
    let mut sidecar = SttSidecar::spawn(AudioSource::SystemAudio, stt_tx, Some(stt_num_threads))?;
    crate::hardware::telemetry::finish(
        session_start,
        crate::hardware::telemetry::PipelineStage::SttSessionStart,
        &crate::hardware::perf_context(&app),
    );
    // STT/RAG scheduling coordination (Phase B): signals RAG indexing to
    // yield while this session runs, on Entry/Standard tier only (no-op
    // otherwise) — see hardware::stt_rag_coordination's module doc.
    crate::hardware::stt_rag_coordination::on_stt_session_started(&app);

    let app_for_pipeline = app.clone();
    let pause_for_pipeline = pause.clone();

    let pipeline_thread = std::thread::Builder::new()
        .name("audio-stt-pipeline".into())
        .spawn(move || {
            // Forward audio chunks to the sidecar and levels to the UI, on this
            // thread, while a second thread below drains STT events. Two separate
            // threads are required so writing audio to the sidecar's stdin never
            // blocks waiting for its stdout to be read (see docs/progress.md Step 4).
            let stt_events_app = app_for_pipeline.clone();
            let events_thread = std::thread::Builder::new()
                .name("stt-events-forwarder".into())
                .spawn(move || {
                    // First-partial/first-final latency, measured from this
                    // forwarder thread's own start (which begins essentially
                    // at session start) to the first occurrence of each
                    // event kind — the number the user actually experiences
                    // (audio flowing -> text appearing), not a cross-process
                    // clock reconciliation with the Python sidecar's own
                    // monotonic timestamps.
                    let stt_clock = crate::hardware::telemetry::Stopwatch::start();
                    let mut first_partial_logged = false;
                    let mut first_final_logged = false;

                    for event in stt_rx.iter() {
                        if !first_partial_logged && event.kind == crate::stt::SttEventKind::Partial {
                            first_partial_logged = true;
                            crate::hardware::telemetry::log_stage_ms(
                                crate::hardware::telemetry::PipelineStage::SttFirstPartial,
                                stt_clock.elapsed().as_millis(),
                                &crate::hardware::perf_context(&stt_events_app),
                            );
                        }
                        if !first_final_logged && event.kind == crate::stt::SttEventKind::Final {
                            first_final_logged = true;
                            crate::hardware::telemetry::log_stage_ms(
                                crate::hardware::telemetry::PipelineStage::SttFinal,
                                stt_clock.elapsed().as_millis(),
                                &crate::hardware::perf_context(&stt_events_app),
                            );
                        }

                        let state = stt_events_app.state::<AppState>();
                        let segment = state
                            .transcript
                            .lock()
                            .ok()
                            .and_then(|mut manager| manager.apply_event(event));
                        if let Some(segment) = segment {
                            let _ = stt_events_app.emit("transcript:update", &segment);
                        }
                    }
                })
                .ok();

            // The loop itself lives in `audio::pipeline` so that the headless
            // `pipeline_test` binary drives the same code rather than a copy.
            crate::audio::run_stt_pipeline(audio_rx, sidecar, pause_for_pipeline, |chunk| {
                let _ = app_for_pipeline.emit(
                    "audio:level",
                    AudioLevelEvent {
                        source: chunk.source,
                        rms_level: chunk.rms_level,
                    },
                );
            });

            if let Some(handle) = events_thread {
                let _ = handle.join();
            }
        })
        .map_err(|e| e.to_string())?;

    session.stop_signal = Some(stop);
    session.pause_signal = Some(pause);
    session.system_audio_thread = Some(audio_thread);
    session.pipeline_thread = Some(pipeline_thread);
    session.recording_state = RecordingState::Recording;

    let _ = app.emit(
        "recording:state",
        RecordingStateEvent {
            state: RecordingState::Recording,
        },
    );
    log::info!("start_system_audio_capture: recording started");

    Ok(())
}

/// Pauses recording: audio capture keeps running internally (so the OS device
/// buffer never overflows) but no audio reaches the STT sidecar or the UI meter,
/// and no transcript segment changes. The sidecar process is left running so
/// resuming is instant and the transcript-so-far is untouched.
#[tauri::command]
pub fn pause_recording(app: tauri::AppHandle, state: State<'_, AppState>) -> Result<(), String> {
    log::info!("pause_recording: invoked");
    let mut session = state.capture.lock().map_err(|e| e.to_string())?;
    let Some(pause) = session.pause_signal.as_ref() else {
        return Err("no active recording to pause".into());
    };
    if session.recording_state != RecordingState::Recording {
        return Err(format!(
            "cannot pause from state {:?}",
            session.recording_state
        ));
    }
    pause.set_paused(true);
    session.recording_state = RecordingState::Paused;
    drop(session);

    {
        let mut transcript = state.transcript.lock().map_err(|e| e.to_string())?;
        transcript.mark_paused();
    }

    let _ = app.emit(
        "recording:state",
        RecordingStateEvent {
            state: RecordingState::Paused,
        },
    );
    log::info!("pause_recording: done");
    Ok(())
}

#[tauri::command]
pub fn resume_recording(app: tauri::AppHandle, state: State<'_, AppState>) -> Result<(), String> {
    log::info!("resume_recording: invoked");
    let mut session = state.capture.lock().map_err(|e| e.to_string())?;
    let Some(pause) = session.pause_signal.as_ref() else {
        return Err("no active recording to resume".into());
    };
    if session.recording_state != RecordingState::Paused {
        return Err(format!(
            "cannot resume from state {:?}",
            session.recording_state
        ));
    }
    pause.set_paused(false);
    session.recording_state = RecordingState::Recording;
    drop(session);

    {
        let mut transcript = state.transcript.lock().map_err(|e| e.to_string())?;
        transcript.mark_resumed();
    }

    let _ = app.emit(
        "recording:state",
        RecordingStateEvent {
            state: RecordingState::Recording,
        },
    );
    log::info!("resume_recording: done");
    Ok(())
}

/// Stops recording: halts WASAPI capture, flushes and finalizes the STT sidecar
/// (so any in-progress utterance is finalized rather than dropped), and marks the
/// session as completed. Does not contact the backend — that only happens if/when
/// the user explicitly clicks "Analyze Interview".
#[tauri::command]
pub fn stop_audio_capture(app: tauri::AppHandle, state: State<'_, AppState>) -> Result<(), String> {
    log::info!("stop_audio_capture: invoked");
    // Take the handles out and drop the lock *before* joining threads below —
    // joining can block for as long as the STT sidecar takes to flush and exit,
    // and holding `state.capture` for that whole span would deadlock every other
    // recording command (get_recording_state, pause/resume, a fresh start) that
    // also needs this same mutex while Stop is still in flight.
    let (pause_signal, stop_signal, system_audio_thread, mic_thread, pipeline_thread) = {
        let mut session = state.capture.lock().map_err(|e| e.to_string())?;
        session.recording_state = RecordingState::Stopped;
        (
            session.pause_signal.take(),
            session.stop_signal.take(),
            session.system_audio_thread.take(),
            session.mic_thread.take(),
            session.pipeline_thread.take(),
        )
    };

    if let Some(pause) = pause_signal {
        // Make sure a paused pipeline thread doesn't sit forever skipping chunks;
        // stopping the capture thread below closes its channel either way, but
        // un-pausing first ensures any final in-flight chunk still reaches STT.
        pause.set_paused(false);
    }
    if let Some(stop) = stop_signal {
        stop.stop();
    }
    if let Some(handle) = system_audio_thread {
        let _ = handle.join();
    }
    if let Some(handle) = mic_thread {
        let _ = handle.join();
    }
    if let Some(handle) = pipeline_thread {
        let _ = handle.join();
    }

    {
        let mut transcript = state.transcript.lock().map_err(|e| e.to_string())?;
        transcript.mark_stopped();
    }

    // STT/RAG scheduling coordination (Phase B): releases the throttle this
    // session may have activated. Safe no-op if it never did (different
    // tier/mode, or this call races a start that hasn't incremented yet —
    // see on_stt_session_ended's own guard against underflow).
    crate::hardware::stt_rag_coordination::on_stt_session_ended(&app);

    let _ = app.emit(
        "recording:state",
        RecordingStateEvent {
            state: RecordingState::Stopped,
        },
    );
    log::info!("stop_audio_capture: done");
    Ok(())
}

#[tauri::command]
pub fn get_current_session(state: State<'_, AppState>) -> Result<InterviewSession, String> {
    let transcript = state.transcript.lock().map_err(|e| e.to_string())?;
    Ok(transcript.session().clone())
}

#[tauri::command]
pub fn get_recording_state(state: State<'_, AppState>) -> Result<RecordingState, String> {
    let session = state.capture.lock().map_err(|e| e.to_string())?;
    Ok(session.recording_state)
}

/// Resets everything to start a brand new interview: any previous recording must
/// already be stopped (recording_state must not be Recording/Paused).
#[tauri::command]
pub fn start_new_interview(state: State<'_, AppState>) -> Result<(), String> {
    let mut session = state.capture.lock().map_err(|e| e.to_string())?;
    if matches!(
        session.recording_state,
        RecordingState::Recording | RecordingState::Paused
    ) {
        return Err("stop the current recording before starting a new interview".into());
    }
    session.recording_state = RecordingState::Idle;
    session.pause_signal = None;
    session.stop_signal = None;
    drop(session);

    let mut transcript = state.transcript.lock().map_err(|e| e.to_string())?;
    transcript.clear();
    Ok(())
}

#[tauri::command]
pub fn clear_transcript(state: State<'_, AppState>) -> Result<(), String> {
    let mut transcript = state.transcript.lock().map_err(|e| e.to_string())?;
    transcript.clear();
    Ok(())
}

fn format_hh_mm_ss(total_ms: u64) -> String {
    let total_secs = total_ms / 1000;
    let hours = total_secs / 3600;
    let minutes = (total_secs % 3600) / 60;
    let seconds = total_secs % 60;
    if hours > 0 {
        format!("{hours:02}:{minutes:02}:{seconds:02}")
    } else {
        format!("{minutes:02}:{seconds:02}")
    }
}

fn iso8601(ms: u64) -> String {
    // Minimal dependency-free ISO-8601-ish UTC timestamp (date is not computed;
    // we keep this local-storage-only export simple and avoid pulling in a full
    // date/time crate just for file headers/JSON export metadata).
    let secs = ms / 1000;
    let millis = ms % 1000;
    format!("{secs}.{millis:03}Z")
}

/// Opens a native "Save As" dialog and writes the current transcript as plain
/// text. Runs entirely locally — no network call.
#[tauri::command]
pub fn export_transcript_txt(app: tauri::AppHandle, state: State<'_, AppState>) -> Result<Option<String>, String> {
    let session = {
        let transcript = state.transcript.lock().map_err(|e| e.to_string())?;
        transcript.session().clone()
    };

    let mut out = String::new();
    out.push_str("INTERVIEW TRANSCRIPT\n");
    out.push_str(&format!("Session ID: {}\n", session.id));
    out.push_str(&format!("Started: {}\n", iso8601(session.started_at_ms)));
    if let Some(ended) = session.ended_at_ms {
        out.push_str(&format!("Ended: {}\n", iso8601(ended)));
    }
    out.push_str(&format!("Duration: {}\n", format_hh_mm_ss(session.elapsed_ms())));
    out.push_str(&format!("Words: {}\n\n", session.word_count()));

    for segment in &session.segments {
        let Some(text) = segment.final_text.as_deref() else {
            continue;
        };
        let relative_ms = segment
            .start_time
            .map(|s| (s * 1000.0) as u64)
            .unwrap_or(0);
        out.push_str(&format!("[{}]\n", format_hh_mm_ss(relative_ms)));
        out.push_str(text);
        out.push_str("\n\n");
    }

    let default_name = format!("interview-transcript-{}.txt", session.id);
    let Some(path) = pick_save_path(&app, &default_name, "Text", &["txt"])? else {
        return Ok(None);
    };
    write_file(&path, out.as_bytes())?;
    Ok(Some(path))
}

/// Opens a native "Save As" dialog and writes the current transcript as
/// structured JSON. Runs entirely locally — no network call.
#[tauri::command]
pub fn export_transcript_json(app: tauri::AppHandle, state: State<'_, AppState>) -> Result<Option<String>, String> {
    let session = {
        let transcript = state.transcript.lock().map_err(|e| e.to_string())?;
        transcript.session().clone()
    };

    #[derive(serde::Serialize)]
    struct ExportSegment {
        timestamp: String,
        source: AudioSource,
        text: String,
    }

    #[derive(serde::Serialize)]
    struct ExportPayload {
        #[serde(rename = "sessionId")]
        session_id: String,
        #[serde(rename = "startedAt")]
        started_at: String,
        #[serde(rename = "endedAt")]
        ended_at: Option<String>,
        #[serde(rename = "durationMs")]
        duration_ms: u64,
        #[serde(rename = "wordCount")]
        word_count: usize,
        segments: Vec<ExportSegment>,
    }

    let payload = ExportPayload {
        session_id: session.id.clone(),
        started_at: iso8601(session.started_at_ms),
        ended_at: session.ended_at_ms.map(iso8601),
        duration_ms: session.elapsed_ms(),
        word_count: session.word_count(),
        segments: session
            .segments
            .iter()
            .filter_map(|s| {
                s.final_text.as_ref().map(|text| ExportSegment {
                    timestamp: iso8601(s.timestamp),
                    source: s.source,
                    text: text.clone(),
                })
            })
            .collect(),
    };

    let json = serde_json::to_string_pretty(&payload).map_err(|e| e.to_string())?;

    let default_name = format!("interview-transcript-{}.json", session.id);
    let Some(path) = pick_save_path(&app, &default_name, "JSON", &["json"])? else {
        return Ok(None);
    };
    write_file(&path, json.as_bytes())?;
    Ok(Some(path))
}

fn pick_save_path(
    app: &tauri::AppHandle,
    default_name: &str,
    filter_name: &str,
    extensions: &[&str],
) -> Result<Option<String>, String> {
    use tauri_plugin_dialog::DialogExt;

    let path = app
        .dialog()
        .file()
        .set_file_name(default_name)
        .add_filter(filter_name, extensions)
        .blocking_save_file();

    Ok(path.map(|p| p.to_string()))
}

fn write_file(path: &str, contents: &[u8]) -> Result<(), String> {
    let mut file = std::fs::File::create(path).map_err(|e| e.to_string())?;
    file.write_all(contents).map_err(|e| e.to_string())?;
    Ok(())
}

/// Quick liveness probe used by the UI's "Backend: Connected/Offline" indicator.
/// Never called automatically as a side effect of recording — only polled by the
/// frontend on an interval / on demand so the user can see connectivity status.
#[tauri::command]
pub async fn check_backend_connection() -> Result<bool, String> {
    let client = BackendClient::new();
    Ok(client.health_check().await.is_ok())
}

/// Runs the full Step 10 analysis pipeline: extract question/answer pairs
/// from the finalized transcript (deterministic, local, no LLM — see
/// `crate::analyzer`), run a local RAG search for each question (local, see
/// `crate::rag::RetrievalPlanner`), then stream the resulting
/// question+context set to the backend for LLM analysis. Only reachable from
/// the "Analyze Interview" button on the post-stop summary screen — never
/// called automatically when recording stops. Sends text only (transcript-
/// derived question/answer text plus retrieved chunk text); no audio, no
/// original documents, no embeddings, no vector database.
///
/// Streams progress as `analysis:progress` Tauri events (one per SSE event
/// from the backend) so the frontend can show incremental status without the
/// command needing to return until the whole analysis finishes.
#[tauri::command]
pub async fn analyze_interview(
    app: tauri::AppHandle,
    state: State<'_, AppState>,
    role: Option<String>,
    company: Option<String>,
    job_description: Option<String>,
) -> Result<crate::backend::OverallInterviewAnalysis, String> {
    let session = {
        let transcript = state.transcript.lock().map_err(|e| e.to_string())?;
        transcript.session().clone()
    };

    if session.segments.is_empty() {
        return Err("cannot analyze an empty transcript".into());
    }

    let qa_pairs = crate::analyzer::extract_question_answers(&session);

    // Tier-driven top_k/similarity_threshold/max_context_chars, but no
    // `.with_timeout()` — this offline analysis path intentionally keeps the
    // client's generous default HTTP budget rather than the tight
    // live-answer timeout, since there's no user waiting on an immediate
    // answer here. `_checked` once here (not per qa_pair in the loop below)
    // — analysis-start is the checkpoint, not each of its many retrievals.
    let cfg = crate::hardware::effective_config_checked(&app);
    let planner = crate::rag::RetrievalPlanner::new().with_config(
        cfg.rag_top_k,
        cfg.rag_similarity_threshold,
        cfg.rag_max_context_chars,
    );
    let mut wire_question_answers = Vec::with_capacity(qa_pairs.len());
    for pair in &qa_pairs {
        let results = planner.plan_for_question(&pair.question).await;
        wire_question_answers.push(crate::backend::WireQuestionAnswer {
            question_id: pair.question_id.clone(),
            question: pair.question.clone(),
            candidate_answer: pair.candidate_answer.clone(),
            timestamp: pair.timestamp.clone(),
            retrieved_context: results
                .into_iter()
                .map(|r| crate::backend::WireRetrievedChunk {
                    text: r.text,
                    source_filename: r.metadata.filename,
                    document_type: r.metadata.document_type,
                    score: r.score,
                })
                .collect(),
        });
    }

    let request = build_analysis_request(&session, role, company, job_description, wire_question_answers);

    let client = BackendClient::new();
    let app_for_events = app.clone();
    client
        .analyze_stream(&request, move |event| {
            let _ = app_for_events.emit("analysis:progress", event);
        })
        .await
}

fn build_analysis_request(
    session: &InterviewSession,
    role: Option<String>,
    company: Option<String>,
    job_description: Option<String>,
    question_answers: Vec<crate::backend::WireQuestionAnswer>,
) -> InterviewAnalysisRequest {
    let segments = session
        .segments
        .iter()
        .filter_map(|segment| wire_segment(session, segment))
        .collect();

    InterviewAnalysisRequest {
        session_id: session.id.clone(),
        role,
        company,
        job_description,
        candidate_context: None,
        transcript: crate::backend::WireTranscript {
            duration_seconds: session.elapsed_ms() / 1000,
            segments,
        },
        question_answers,
    }
}

fn wire_segment(
    session: &InterviewSession,
    segment: &TranscriptSegment,
) -> Option<crate::backend::WireTranscriptSegment> {
    let text = segment.final_text.clone()?;
    let relative_ms = segment.timestamp.saturating_sub(session.started_at_ms);
    Some(crate::backend::WireTranscriptSegment {
        timestamp: format_relative_timestamp(relative_ms),
        source: match segment.source {
            AudioSource::SystemAudio => crate::backend::WireAudioSource::SystemAudio,
            AudioSource::Microphone => crate::backend::WireAudioSource::Microphone,
        },
        text,
    })
}

fn format_relative_timestamp(ms: u64) -> String {
    let total_secs = ms / 1000;
    let hours = total_secs / 3600;
    let minutes = (total_secs % 3600) / 60;
    let seconds = total_secs % 60;
    if hours > 0 {
        format!("{hours:02}:{minutes:02}:{seconds:02}")
    } else {
        format!("{minutes:02}:{seconds:02}")
    }
}

fn rag_unavailable_err() -> String {
    "RAG service is not available (it may still be starting up, or its Python \
     environment was not set up — see packages/rag/README.md)"
        .to_string()
}

/// Every RAG command below checks `state.rag_service` is `Some` before making
/// any HTTP call — this is what makes "RAG unavailable" a clean user-facing
/// error rather than a raw connection-refused message, and it's also what lets
/// the rest of the app (recording, transcript, export, analyze) keep working
/// normally even if the RAG service's environment was never set up.
fn ensure_rag_available(state: &State<'_, AppState>) -> Result<(), String> {
    let slot = state.rag_service.lock().map_err(|e| e.to_string())?;
    if slot.is_none() {
        return Err(rag_unavailable_err());
    }
    Ok(())
}

#[tauri::command]
pub async fn check_rag_connection(state: State<'_, AppState>) -> Result<bool, String> {
    if ensure_rag_available(&state).is_err() {
        return Ok(false);
    }
    let client = RagClient::new();
    Ok(client.health_check().await.is_ok())
}

/// New Interview setup page's auto-analysis: summarizes pasted/uploaded CV
/// and job-description text into a short "Interview Focus" for the setup
/// page to display. Pure text-in/JSON-out through the FastAPI backend — no
/// RAG/embedding involved, so unlike the commands below it does not require
/// the RAG service to be available.
#[tauri::command]
pub async fn analyze_setup_context(
    resume_text: Option<String>,
    job_description_text: Option<String>,
) -> Result<SetupAnalysisResponse, String> {
    let client = BackendClient::new();
    client
        .analyze_setup(&SetupAnalysisRequest {
            resume_text,
            job_description_text,
        })
        .await
}

#[tauri::command]
pub async fn upload_document(
    state: State<'_, AppState>,
    filename: String,
    bytes: Vec<u8>,
    document_type: String,
    agent_id: Option<String>,
) -> Result<DocumentMetadata, String> {
    ensure_rag_available(&state)?;
    let client = RagClient::new();
    client
        .upload_document(filename, bytes, &document_type, agent_id.as_deref())
        .await
}

/// Polled by the New Interview setup page after uploading a PDF/DOCX resume
/// or job description, so its auto-analysis summary can use the file's real
/// extracted text instead of being limited to pasted/plain-text input.
/// Returns `None` while the RAG service is still extracting/chunking/
/// embedding the document — the frontend treats that as "try again shortly."
#[tauri::command]
pub async fn get_document_text(
    state: State<'_, AppState>,
    document_id: String,
) -> Result<Option<String>, String> {
    ensure_rag_available(&state)?;
    let client = RagClient::new();
    client.get_document_text(&document_id).await
}

#[tauri::command]
pub async fn list_documents(
    state: State<'_, AppState>,
    agent_id: Option<String>,
) -> Result<Vec<DocumentMetadata>, String> {
    ensure_rag_available(&state)?;
    let client = RagClient::new();
    client.list_documents(agent_id.as_deref()).await
}

#[tauri::command]
pub async fn delete_document(state: State<'_, AppState>, document_id: String) -> Result<(), String> {
    ensure_rag_available(&state)?;
    let client = RagClient::new();
    client.delete_document(&document_id).await
}

#[tauri::command]
pub async fn clear_knowledge_base(state: State<'_, AppState>, agent_id: Option<String>) -> Result<(), String> {
    ensure_rag_available(&state)?;
    let client = RagClient::new();
    client.clear_knowledge_base(agent_id.as_deref()).await
}

#[tauri::command]
pub async fn knowledge_base_status(
    state: State<'_, AppState>,
    agent_id: Option<String>,
) -> Result<KnowledgeBaseStatus, String> {
    ensure_rag_available(&state)?;
    let client = RagClient::new();
    client.knowledge_base_status(agent_id.as_deref()).await
}

#[tauri::command]
pub async fn search_knowledge_base(
    state: State<'_, AppState>,
    query: String,
    top_k: u32,
    agent_id: Option<String>,
) -> Result<SearchResponse, String> {
    ensure_rag_available(&state)?;
    let client = RagClient::new();
    client.search(&query, top_k, agent_id.as_deref()).await
}
