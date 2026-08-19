//! The one live "ask" command shared by every Custom Agent — predefined-role
//! or fully custom — instead of a command per role. Mirrors Sales Mode's
//! `ask_sales_question` (optional agent-scoped retrieval -> one LLM call via
//! the backend's generic `/api/v1/agents/ask/stream` -> stream deltas to the
//! overlay), parameterized by the `Agent` record looked up from
//! `AgentStore` instead of hardcoded per-mode request fields.

use tauri::{AppHandle, Emitter, State};

use crate::backend::{
    AgentAskRequest, AgentConversationTurn as WireConversationTurn, AgentPersonalization,
    AgentRetrievedChunk, BackendClient,
};
use crate::rag::RetrievalPlanner;

use super::model::{Agent, AnswerFormat, AnswerLength, LiveAssistance, Personalization, ResponseStyle};
use super::store::AgentStore;

// Retrieval's top_k/similarity_threshold/max_context_chars/timeout are all
// hardware-tier-driven (hardware::PerformanceManager::effective_config) —
// see hardware::manager for the tier table.
const MAX_HISTORY_TURNS: usize = 6;

#[derive(Debug, Clone, serde::Deserialize)]
pub struct PriorTurn {
    pub question: String,
    pub answer: String,
}

fn role_wire_value(role: super::model::PredefinedRole) -> String {
    // Matches serde's SCREAMING_SNAKE_CASE rendering of PredefinedRole
    // (see model.rs) — serialize through serde_json rather than hand-listing
    // the mapping a second time, so the two can never drift.
    serde_json::to_value(role)
        .ok()
        .and_then(|v| v.as_str().map(str::to_string))
        .unwrap_or_default()
}

fn answer_length_wire_value(v: AnswerLength) -> String {
    match v {
        AnswerLength::Concise => "concise",
        AnswerLength::Balanced => "balanced",
        AnswerLength::Detailed => "detailed",
        AnswerLength::Adaptive => "adaptive",
    }
    .to_string()
}

fn response_style_wire_value(v: ResponseStyle) -> String {
    match v {
        ResponseStyle::Natural => "natural",
        ResponseStyle::Professional => "professional",
        ResponseStyle::Friendly => "friendly",
        ResponseStyle::Technical => "technical",
    }
    .to_string()
}

fn answer_format_wire_value(v: AnswerFormat) -> String {
    match v {
        AnswerFormat::Adaptive => "adaptive",
        AnswerFormat::Paragraph => "paragraph",
        AnswerFormat::Bullets => "bullets",
        AnswerFormat::StepByStep => "step_by_step",
    }
    .to_string()
}

fn live_assistance_wire_value(v: LiveAssistance) -> String {
    match v {
        LiveAssistance::Manual => "manual",
        LiveAssistance::Suggest => "suggest",
        LiveAssistance::Auto => "auto",
    }
    .to_string()
}

fn personalization_wire(p: Personalization) -> AgentPersonalization {
    AgentPersonalization {
        answer_length: answer_length_wire_value(p.answer_length),
        response_style: response_style_wire_value(p.response_style),
        answer_format: answer_format_wire_value(p.answer_format),
        live_assistance: live_assistance_wire_value(p.live_assistance),
    }
}

fn trim_history(turns: Vec<PriorTurn>) -> Vec<WireConversationTurn> {
    let mut history: Vec<WireConversationTurn> = turns
        .into_iter()
        .filter(|t| !t.question.trim().is_empty() && !t.answer.trim().is_empty())
        .map(|t| WireConversationTurn {
            question: t.question.trim().to_string(),
            answer: t.answer.trim().to_string(),
        })
        .collect();
    if history.len() > MAX_HISTORY_TURNS {
        history.drain(..history.len() - MAX_HISTORY_TURNS);
    }
    history
}

fn find_agent(store: &AgentStore, app: &AppHandle, agent_id: &str) -> Result<Agent, String> {
    let mut guard = store.0.lock().map_err(|e| e.to_string())?;
    if guard.is_empty() {
        *guard = super::store::load(app);
    }
    guard
        .iter()
        .find(|a| a.id == agent_id)
        .cloned()
        .ok_or_else(|| format!("no agent with id '{agent_id}'"))
}

/// Runs one live question through the agent's own knowledge base and
/// composed system prompt, streaming the answer via `agent:answer-delta` /
/// `agent:answer-complete` events (mirrors `sales-mode:answer-delta` etc.).
#[tauri::command]
pub async fn ask_agent_question(
    app: AppHandle,
    store: State<'_, AgentStore>,
    agent_id: String,
    question: String,
    history: Option<Vec<PriorTurn>>,
) -> Result<String, String> {
    use crate::hardware::telemetry::{finish, FirstTokenTracker, PipelineStage, Stopwatch};

    let question_to_answer = Stopwatch::start();

    let trimmed = question.trim();
    if trimmed.is_empty() {
        return Err("no question text to send".into());
    }

    let agent = find_agent(&store, &app, &agent_id)?;
    let history = trim_history(history.unwrap_or_default());

    // Scoped to this agent's own knowledge base only — never the global KB
    // or another agent's documents. See rag::RetrievalPlanner::with_agent_scope
    // and packages/rag's agent_id column.
    // `_checked`: natural per-question memory-pressure checkpoint.
    let cfg = crate::hardware::effective_config_checked(&app);
    let planner = RetrievalPlanner::new()
        .with_config(cfg.rag_top_k, cfg.rag_similarity_threshold, cfg.rag_max_context_chars)
        .with_timeout(std::time::Duration::from_millis(cfg.rag_retrieval_timeout_ms))
        .with_agent_scope(agent.id.clone());
    let retrieval_timer = Stopwatch::start();
    let retrieved = planner.plan_for_question(trimmed).await;
    finish(retrieval_timer, PipelineStage::RagRetrieval, &crate::hardware::perf_context(&app));

    let request = AgentAskRequest {
        agent_id: agent.id.clone(),
        agent_name: agent.name.clone(),
        base_role: agent.base_role.map(role_wire_value),
        description: agent.description.clone(),
        custom_instructions: agent.custom_instructions.clone(),
        personalization: personalization_wire(agent.personalization),
        question: trimmed.to_string(),
        conversation_history: history,
        retrieved_context: retrieved
            .into_iter()
            .map(|r| AgentRetrievedChunk {
                text: r.text,
                source_filename: r.metadata.filename,
                document_type: r.metadata.document_type,
                score: r.score,
            })
            .collect(),
    };

    let client = BackendClient::new();
    let app_for_events = app.clone();
    let llm_timer = Stopwatch::start();
    let first_token = FirstTokenTracker::new();
    let first_token_recorder = first_token.recorder();
    let answer = client
        .agent_ask_stream(&request, move |delta| {
            first_token_recorder.mark();
            let _ = app_for_events.emit("agent:answer-delta", delta);
        })
        .await?;

    let ctx = crate::hardware::perf_context(&app);
    if let Some(ms) = first_token.elapsed_ms() {
        crate::hardware::telemetry::log_stage_ms(PipelineStage::LlmFirstToken, ms, &ctx);
    }
    finish(llm_timer, PipelineStage::LlmTotal, &ctx);
    finish(question_to_answer, PipelineStage::QuestionToAnswer, &ctx);

    let _ = app.emit("agent:answer-complete", &answer);
    Ok(answer)
}

#[cfg(test)]
mod tests {
    use super::*;
    use super::super::model::PredefinedRole;

    #[test]
    fn role_wire_value_matches_backend_screaming_snake_case() {
        assert_eq!(role_wire_value(PredefinedRole::Salesperson), "SALESPERSON");
        assert_eq!(role_wire_value(PredefinedRole::SalesEngineer), "SALES_ENGINEER");
        assert_eq!(role_wire_value(PredefinedRole::BusinessAnalyst), "BUSINESS_ANALYST");
    }

    #[test]
    fn answer_format_wire_value_matches_backend_snake_case() {
        assert_eq!(answer_format_wire_value(AnswerFormat::StepByStep), "step_by_step");
        assert_eq!(answer_format_wire_value(AnswerFormat::Adaptive), "adaptive");
    }

    #[test]
    fn personalization_wire_maps_every_field() {
        let p = Personalization {
            answer_length: AnswerLength::Concise,
            response_style: ResponseStyle::Technical,
            answer_format: AnswerFormat::Bullets,
            live_assistance: LiveAssistance::Suggest,
        };
        let wire = personalization_wire(p);
        assert_eq!(wire.answer_length, "concise");
        assert_eq!(wire.response_style, "technical");
        assert_eq!(wire.answer_format, "bullets");
        assert_eq!(wire.live_assistance, "suggest");
    }

    #[test]
    fn trim_history_drops_blank_turns_and_caps_length() {
        let turns: Vec<PriorTurn> = (0..10)
            .map(|i| PriorTurn { question: format!("q{i}"), answer: format!("a{i}") })
            .chain(std::iter::once(PriorTurn { question: "".to_string(), answer: "a".to_string() }))
            .collect();
        let trimmed = trim_history(turns);
        assert_eq!(trimmed.len(), MAX_HISTORY_TURNS);
        // Oldest dropped first — the last MAX_HISTORY_TURNS real turns remain.
        assert_eq!(trimmed.last().unwrap().question, "q9");
    }
}
