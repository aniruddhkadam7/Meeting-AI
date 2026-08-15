//! The `Agent` data model: a predefined-role or fully-custom agent
//! definition, persisted on disk. This is the one record type Custom Agents
//! is built around — see `commands.rs` for CRUD, `ask.rs` for how it drives
//! a live question, and `history.rs` for its per-agent conversation archive.

use serde::{Deserialize, Serialize};

/// The 8 predefined professional roles from the Custom Agents spec. Matches
/// `apps/backend/app/schemas/agent_ask.py::PredefinedRole` string-for-string
/// (SCREAMING_SNAKE_CASE on the wire) so a request never needs translating.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "SCREAMING_SNAKE_CASE")]
pub enum PredefinedRole {
    Salesperson,
    SalesEngineer,
    Consultant,
    Recruiter,
    CustomerSupport,
    ProjectManager,
    BusinessAnalyst,
    TechnicalSupport,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum AnswerLength {
    Concise,
    Balanced,
    Detailed,
    Adaptive,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum ResponseStyle {
    Natural,
    Professional,
    Friendly,
    Technical,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum AnswerFormat {
    Adaptive,
    Paragraph,
    Bullets,
    StepByStep,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum LiveAssistance {
    Manual,
    Suggest,
    Auto,
}

/// Defaults match the spec exactly: Natural, Adaptive length, Adaptive
/// format, Manual live assistance — the same "manual"/no-auto-send default
/// Interview Mode's `autoAI: false` already uses (see
/// `apps/desktop/src/overlaySettings.ts`), not a new behavior invented here.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Personalization {
    pub answer_length: AnswerLength,
    pub response_style: ResponseStyle,
    pub answer_format: AnswerFormat,
    pub live_assistance: LiveAssistance,
}

impl Default for Personalization {
    fn default() -> Self {
        Self {
            answer_length: AnswerLength::Adaptive,
            response_style: ResponseStyle::Natural,
            answer_format: AnswerFormat::Adaptive,
            live_assistance: LiveAssistance::Manual,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn defaults_match_the_spec_exactly() {
        // Natural, Adaptive length, Adaptive format, Manual live assistance —
        // per the Custom Agents spec's stated defaults, and matching
        // Interview Mode's existing autoAI:false ("manual") default.
        let p = Personalization::default();
        assert_eq!(p.answer_length, AnswerLength::Adaptive);
        assert_eq!(p.response_style, ResponseStyle::Natural);
        assert_eq!(p.answer_format, AnswerFormat::Adaptive);
        assert_eq!(p.live_assistance, LiveAssistance::Manual);
    }

    #[test]
    fn predefined_role_serializes_as_screaming_snake_case() {
        // Must match apps/backend/app/schemas/agent_ask.py::PredefinedRole
        // string-for-string so a request never needs translating.
        let value = serde_json::to_value(PredefinedRole::SalesEngineer).unwrap();
        assert_eq!(value.as_str(), Some("SALES_ENGINEER"));
        let value = serde_json::to_value(PredefinedRole::CustomerSupport).unwrap();
        assert_eq!(value.as_str(), Some("CUSTOMER_SUPPORT"));
    }

    #[test]
    fn answer_format_serializes_as_snake_case() {
        let value = serde_json::to_value(AnswerFormat::StepByStep).unwrap();
        assert_eq!(value.as_str(), Some("step_by_step"));
    }

    #[test]
    fn agent_round_trips_through_json_with_optional_fields_absent() {
        let agent = Agent {
            id: "agent-1".to_string(),
            name: "My Agent".to_string(),
            base_role: None,
            description: None,
            custom_instructions: None,
            personalization: Personalization::default(),
            created_at_ms: 1,
            updated_at_ms: 1,
        };
        let json = serde_json::to_string(&agent).unwrap();
        let parsed: Agent = serde_json::from_str(&json).unwrap();
        assert_eq!(parsed.id, "agent-1");
        assert!(parsed.base_role.is_none());
    }

    #[test]
    fn agent_missing_personalization_field_deserializes_to_default() {
        // Older/hand-written JSON without a personalization key must not
        // fail to load — falls back to the default via #[serde(default)].
        let json = r#"{
            "id": "agent-1", "name": "My Agent",
            "createdAtMs": 1, "updatedAtMs": 1
        }"#;
        let parsed: Agent = serde_json::from_str(json).unwrap();
        assert_eq!(parsed.personalization, Personalization::default());
    }
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Agent {
    pub id: String,
    pub name: String,
    #[serde(default)]
    pub base_role: Option<PredefinedRole>,
    #[serde(default)]
    pub description: Option<String>,
    #[serde(default)]
    pub custom_instructions: Option<String>,
    #[serde(default)]
    pub personalization: Personalization,
    pub created_at_ms: u64,
    pub updated_at_ms: u64,
}
