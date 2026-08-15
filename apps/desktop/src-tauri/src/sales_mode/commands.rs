//! Tauri commands for Sales Mode: overlay window lifecycle, the live
//! suggestion ("ask") flow, live tracking of requirements/objections/
//! commitments, and ending a call (summary + archive to history).
//!
//! Audio capture/transcript itself reuses the exact same commands Interview
//! Mode uses (`start_system_audio_capture`, `stop_audio_capture`,
//! `transcript:update` events) — SYSTEM_AUDIO is the customer, MICROPHONE is
//! the rep. Nothing sales-specific needed duplicating there.

use std::time::Duration;

use tauri::{AppHandle, Emitter, State};

use crate::backend::{
    BackendClient, SalesAskRequest, SalesConversationTurn, SalesRetrievedChunk, SalesSummaryRequest,
    SalesTurnIn,
};
use crate::overlay_window;
use crate::rag::RetrievalPlanner;
use crate::state::{AppState, SalesTrackedItem};

use super::SALES_OVERLAY_LABEL;

const SALES_TOP_K: u32 = 3;
const RETRIEVAL_TIMEOUT: Duration = Duration::from_millis(1_200);
const MAX_HISTORY_TURNS: usize = 6;

#[derive(Debug, Clone, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct SalesAskOptions {
    #[serde(default = "default_answer_length")]
    pub answer_length: String,
    #[serde(default = "default_response_style")]
    pub response_style: String,
    #[serde(default)]
    pub customer_name: Option<String>,
    #[serde(default)]
    pub company_name: Option<String>,
    #[serde(default = "default_call_stage")]
    pub call_stage: String,
}

fn default_answer_length() -> String {
    "default".to_string()
}
fn default_response_style() -> String {
    "natural".to_string()
}
fn default_call_stage() -> String {
    "discovery".to_string()
}

impl Default for SalesAskOptions {
    fn default() -> Self {
        Self {
            answer_length: default_answer_length(),
            response_style: default_response_style(),
            customer_name: None,
            company_name: None,
            call_stage: default_call_stage(),
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
pub async fn show_sales_overlay(app: AppHandle) -> Result<overlay_window::OverlayCaptureStatus, String> {
    run_on_main(&app, |app| {
        overlay_window::show_overlay_window(app, SALES_OVERLAY_LABEL, "REDLY Sales — Overlay")
    })
    .await
}

#[tauri::command]
pub async fn hide_sales_overlay(app: AppHandle) -> Result<(), String> {
    run_on_main(&app, |app| overlay_window::close_overlay_window(app, SALES_OVERLAY_LABEL)).await
}

#[tauri::command]
pub async fn toggle_sales_overlay(app: AppHandle) -> Result<overlay_window::OverlayCaptureStatus, String> {
    run_on_main(&app, |app| {
        overlay_window::toggle_overlay_window(app, SALES_OVERLAY_LABEL, "REDLY Sales — Overlay")
    })
    .await
}

/// Runs the live "suggest a response" flow for the rep's question, mirroring
/// Interview Mode's `ask_interview_question` (optional retrieval -> one LLM
/// call -> stream). Streams `sales-mode:answer-delta` / `answer-complete`.
#[tauri::command]
pub async fn ask_sales_question(
    app: AppHandle,
    _state: State<'_, AppState>,
    question: String,
    options: Option<SalesAskOptions>,
    history: Option<Vec<PriorTurn>>,
) -> Result<String, String> {
    let trimmed = question.trim();
    if trimmed.is_empty() {
        return Err("no question text to send".into());
    }
    let options = options.unwrap_or_default();
    let history = trim_history(history.unwrap_or_default());

    let planner = RetrievalPlanner::new()
        .with_config(SALES_TOP_K, 0.3, 3_000)
        .with_timeout(RETRIEVAL_TIMEOUT);
    let retrieved = planner.plan_for_question(trimmed).await;

    let request = SalesAskRequest {
        question: trimmed.to_string(),
        conversation_history: history,
        retrieved_context: retrieved
            .into_iter()
            .map(|r| SalesRetrievedChunk {
                text: r.text,
                source_filename: r.metadata.filename,
                document_type: r.metadata.document_type,
                score: r.score,
            })
            .collect(),
        customer_name: options.customer_name,
        company_name: options.company_name,
        call_stage: options.call_stage,
        answer_length: options.answer_length,
        response_style: options.response_style,
    };

    let client = BackendClient::new();
    let app_for_events = app.clone();
    let answer = client
        .sales_ask_stream(&request, move |delta| {
            let _ = app_for_events.emit("sales-mode:answer-delta", delta);
        })
        .await?;

    let _ = app.emit("sales-mode:answer-complete", &answer);
    Ok(answer)
}

fn trim_history(turns: Vec<PriorTurn>) -> Vec<SalesConversationTurn> {
    let mut history: Vec<SalesConversationTurn> = turns
        .into_iter()
        .filter(|t| !t.question.trim().is_empty() && !t.answer.trim().is_empty())
        .map(|t| SalesConversationTurn {
            question: t.question.trim().to_string(),
            answer: t.answer.trim().to_string(),
        })
        .collect();
    if history.len() > MAX_HISTORY_TURNS {
        history.drain(..history.len() - MAX_HISTORY_TURNS);
    }
    history
}

/// Tracked-item kind for `track_sales_item` — matches the three lists the
/// overlay shows live during the call.
#[derive(Debug, Clone, Copy, serde::Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum SalesItemKind {
    Requirement,
    Objection,
    Commitment,
}

#[tauri::command]
pub fn track_sales_item(state: State<'_, AppState>, kind: SalesItemKind, text: String) -> Result<(), String> {
    let trimmed = text.trim();
    if trimmed.is_empty() {
        return Err("cannot track an empty item".into());
    }
    let mut session = state.sales_session.lock().map_err(|e| e.to_string())?;
    let item = SalesTrackedItem { text: trimmed.to_string() };
    match kind {
        SalesItemKind::Requirement => session.requirements.push(item),
        SalesItemKind::Objection => session.objections.push(item),
        SalesItemKind::Commitment => session.commitments.push(item),
    }
    Ok(())
}

#[tauri::command]
pub fn clear_sales_session(state: State<'_, AppState>) -> Result<(), String> {
    let mut session = state.sales_session.lock().map_err(|e| e.to_string())?;
    *session = Default::default();
    Ok(())
}

#[derive(Debug, serde::Deserialize)]
pub struct SalesTurnPayload {
    pub speaker: String,
    pub text: String,
}

/// Builds a structured end-of-call summary from the transcript + tracked
/// items. The caller (frontend) archives the result to Sales history via
/// `archive_sales_call`, which is what actually needs `started_at_ms`.
#[tauri::command]
pub async fn end_sales_call(
    state: State<'_, AppState>,
    turns: Vec<SalesTurnPayload>,
    customer_name: Option<String>,
    company_name: Option<String>,
) -> Result<crate::backend::SalesCallSummary, String> {
    let (requirements, objections, commitments) = {
        let session = state.sales_session.lock().map_err(|e| e.to_string())?;
        (
            session.requirements.iter().map(|i| i.text.clone()).collect::<Vec<_>>(),
            session.objections.iter().map(|i| i.text.clone()).collect::<Vec<_>>(),
            session.commitments.iter().map(|i| i.text.clone()).collect::<Vec<_>>(),
        )
    };

    let request = SalesSummaryRequest {
        turns: turns
            .iter()
            .map(|t| SalesTurnIn { speaker: t.speaker.clone(), text: t.text.clone() })
            .collect(),
        requirements: requirements.clone(),
        objections: objections.clone(),
        commitments: commitments.clone(),
        customer_name: customer_name.clone(),
        company_name: company_name.clone(),
    };

    let client = BackendClient::new();
    let summary = client.sales_summarize(&request).await?;

    Ok(summary)
}
