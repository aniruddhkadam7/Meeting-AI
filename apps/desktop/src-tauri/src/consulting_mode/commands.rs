//! Tauri commands for Consulting Mode: overlay window lifecycle, the live
//! ask flow (with cross-session `engagement_context`), live tracking of
//! risks/assumptions/decisions/dependencies/action items, and ending a
//! session (structured notes + archive to history).
//!
//! Audio capture/transcript reuses the same commands Interview Mode and
//! Sales Mode use — SYSTEM_AUDIO is the client, MICROPHONE is the consultant.

use std::time::Duration;

use tauri::{AppHandle, Emitter, State};

use crate::backend::{
    BackendClient, ConsultingAskRequest, ConsultingConversationTurn, ConsultingRetrievedChunk,
    ConsultingSummaryRequest, ConsultingTurnIn,
};
use crate::overlay_window;
use crate::rag::RetrievalPlanner;
use crate::state::{AppState, SalesTrackedItem};

use super::CONSULTING_OVERLAY_LABEL;

const CONSULTING_TOP_K: u32 = 3;
const RETRIEVAL_TIMEOUT: Duration = Duration::from_millis(1_200);
const MAX_HISTORY_TURNS: usize = 6;

#[derive(Debug, Clone, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct ConsultingAskOptions {
    #[serde(default = "default_answer_length")]
    pub answer_length: String,
    #[serde(default = "default_response_style")]
    pub response_style: String,
    #[serde(default)]
    pub client_name: Option<String>,
    #[serde(default)]
    pub project_name: Option<String>,
    #[serde(default)]
    pub engagement_context: Option<String>,
}

fn default_answer_length() -> String {
    "default".to_string()
}
fn default_response_style() -> String {
    "natural".to_string()
}

impl Default for ConsultingAskOptions {
    fn default() -> Self {
        Self {
            answer_length: default_answer_length(),
            response_style: default_response_style(),
            client_name: None,
            project_name: None,
            engagement_context: None,
        }
    }
}

#[derive(Debug, Clone, serde::Deserialize)]
pub struct PriorTurn {
    pub question: String,
    pub answer: String,
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

#[tauri::command]
pub async fn show_consulting_overlay(app: AppHandle) -> Result<overlay_window::OverlayCaptureStatus, String> {
    run_on_main(&app, |app| {
        overlay_window::show_overlay_window(app, CONSULTING_OVERLAY_LABEL, "REDLY Consulting — Overlay")
    })
    .await
}

#[tauri::command]
pub async fn hide_consulting_overlay(app: AppHandle) -> Result<(), String> {
    run_on_main(&app, |app| overlay_window::close_overlay_window(app, CONSULTING_OVERLAY_LABEL)).await
}

#[tauri::command]
pub async fn toggle_consulting_overlay(app: AppHandle) -> Result<overlay_window::OverlayCaptureStatus, String> {
    run_on_main(&app, |app| {
        overlay_window::toggle_overlay_window(app, CONSULTING_OVERLAY_LABEL, "REDLY Consulting — Overlay")
    })
    .await
}

#[tauri::command]
pub async fn ask_consulting_question(
    app: AppHandle,
    _state: State<'_, AppState>,
    question: String,
    options: Option<ConsultingAskOptions>,
    history: Option<Vec<PriorTurn>>,
) -> Result<String, String> {
    let trimmed = question.trim();
    if trimmed.is_empty() {
        return Err("no question text to send".into());
    }
    let options = options.unwrap_or_default();
    let history = trim_history(history.unwrap_or_default());

    let planner = RetrievalPlanner::new()
        .with_config(CONSULTING_TOP_K, 0.3, 3_000)
        .with_timeout(RETRIEVAL_TIMEOUT);
    let retrieved = planner.plan_for_question(trimmed).await;

    let request = ConsultingAskRequest {
        question: trimmed.to_string(),
        conversation_history: history,
        retrieved_context: retrieved
            .into_iter()
            .map(|r| ConsultingRetrievedChunk {
                text: r.text,
                source_filename: r.metadata.filename,
                document_type: r.metadata.document_type,
                score: r.score,
            })
            .collect(),
        client_name: options.client_name,
        project_name: options.project_name,
        engagement_context: options.engagement_context,
        answer_length: options.answer_length,
        response_style: options.response_style,
    };

    let client = BackendClient::new();
    let app_for_events = app.clone();
    let answer = client
        .consulting_ask_stream(&request, move |delta| {
            let _ = app_for_events.emit("consulting-mode:answer-delta", delta);
        })
        .await?;

    let _ = app.emit("consulting-mode:answer-complete", &answer);
    Ok(answer)
}

fn trim_history(turns: Vec<PriorTurn>) -> Vec<ConsultingConversationTurn> {
    let mut history: Vec<ConsultingConversationTurn> = turns
        .into_iter()
        .filter(|t| !t.question.trim().is_empty() && !t.answer.trim().is_empty())
        .map(|t| ConsultingConversationTurn {
            question: t.question.trim().to_string(),
            answer: t.answer.trim().to_string(),
        })
        .collect();
    if history.len() > MAX_HISTORY_TURNS {
        history.drain(..history.len() - MAX_HISTORY_TURNS);
    }
    history
}

#[derive(Debug, Clone, Copy, serde::Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum ConsultingItemKind {
    Risk,
    Assumption,
    Decision,
    Dependency,
    ActionItem,
}

#[tauri::command]
pub fn track_consulting_item(
    state: State<'_, AppState>,
    kind: ConsultingItemKind,
    text: String,
) -> Result<(), String> {
    let trimmed = text.trim();
    if trimmed.is_empty() {
        return Err("cannot track an empty item".into());
    }
    let mut session = state.consulting_session.lock().map_err(|e| e.to_string())?;
    let item = SalesTrackedItem { text: trimmed.to_string() };
    match kind {
        ConsultingItemKind::Risk => session.risks.push(item),
        ConsultingItemKind::Assumption => session.assumptions.push(item),
        ConsultingItemKind::Decision => session.decisions.push(item),
        ConsultingItemKind::Dependency => session.dependencies.push(item),
        ConsultingItemKind::ActionItem => session.action_items.push(item),
    }
    Ok(())
}

#[tauri::command]
pub fn clear_consulting_session(state: State<'_, AppState>) -> Result<(), String> {
    let mut session = state.consulting_session.lock().map_err(|e| e.to_string())?;
    *session = Default::default();
    Ok(())
}

#[derive(Debug, serde::Deserialize)]
pub struct ConsultingTurnPayload {
    pub speaker: String,
    pub text: String,
}

/// Ends the session: builds structured notes from the transcript + tracked
/// items. The caller (frontend) is responsible for archiving the result to
/// the engagement's history via `history::archive_consulting_session`, since
/// it also needs the engagement id which this command doesn't know about.
#[tauri::command]
pub async fn end_consulting_session(
    state: State<'_, AppState>,
    turns: Vec<ConsultingTurnPayload>,
    client_name: Option<String>,
    project_name: Option<String>,
) -> Result<crate::backend::ConsultingNote, String> {
    let (risks, assumptions, decisions, dependencies, action_items) = {
        let session = state.consulting_session.lock().map_err(|e| e.to_string())?;
        (
            session.risks.iter().map(|i| i.text.clone()).collect::<Vec<_>>(),
            session.assumptions.iter().map(|i| i.text.clone()).collect::<Vec<_>>(),
            session.decisions.iter().map(|i| i.text.clone()).collect::<Vec<_>>(),
            session.dependencies.iter().map(|i| i.text.clone()).collect::<Vec<_>>(),
            session.action_items.iter().map(|i| i.text.clone()).collect::<Vec<_>>(),
        )
    };

    let request = ConsultingSummaryRequest {
        turns: turns
            .iter()
            .map(|t| ConsultingTurnIn { speaker: t.speaker.clone(), text: t.text.clone() })
            .collect(),
        risks,
        assumptions,
        decisions,
        dependencies,
        action_items,
        client_name,
        project_name,
    };

    let client = BackendClient::new();
    client.consulting_summarize(&request).await
}
