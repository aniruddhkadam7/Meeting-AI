use std::time::Duration;

use serde::{Deserialize, Serialize};

use crate::backend::backend_url;

// Plain snake_case on the wire (no rename) — this struct talks to REDLY
// Cloud's FastAPI backend (app/schemas/agent_sync.py::SyncedAgent), which
// uses snake_case fields with no camelCase alias config, matching every
// other backend wire type in this codebase (see backend::types::*). This is
// distinct from Tauri IPC types (e.g. agents::model::Agent), which use
// `rename_all = "camelCase"` because the frontend JS side expects camelCase
// — the two boundaries have different conventions and must not be confused.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct SyncedAgent {
    pub client_id: String,
    pub name: String,
    #[serde(default)]
    pub base_role: Option<String>,
    #[serde(default)]
    pub description: Option<String>,
    #[serde(default)]
    pub custom_instructions: Option<String>,
    #[serde(default)]
    pub personalization: serde_json::Value,
    pub created_at_ms: u64,
    pub updated_at_ms: u64,
    #[serde(default)]
    pub deleted: bool,
}

#[derive(Debug, Deserialize)]
struct PullResponse {
    agents: Vec<SyncedAgent>,
}

#[derive(Debug, Serialize)]
struct PushRequest<'a> {
    agents: &'a [SyncedAgent],
}

pub struct CloudSyncClient {
    http: reqwest::Client,
    base_url: String,
}

impl CloudSyncClient {
    pub fn new() -> Self {
        crate::tls_init::ensure_installed();
        Self {
            http: reqwest::Client::builder()
                .timeout(Duration::from_secs(20))
                .build()
                .unwrap_or_default(),
            base_url: backend_url(),
        }
    }

    pub async fn push_agents(&self, token: &str, agents: &[SyncedAgent]) -> Result<(), String> {
        if agents.is_empty() {
            return Ok(());
        }
        let url = format!("{}/api/v1/agents/sync/push", self.base_url);
        let response = self
            .http
            .post(&url)
            .bearer_auth(token)
            .json(&PushRequest { agents })
            .send()
            .await
            .map_err(|e| format!("failed to reach REDLY Cloud: {e}"))?;

        if response.status().is_success() {
            Ok(())
        } else {
            Err(format!("agent push failed ({})", response.status()))
        }
    }

    pub async fn pull_agents(&self, token: &str) -> Result<Vec<SyncedAgent>, String> {
        let url = format!("{}/api/v1/agents/sync/pull", self.base_url);
        let response = self
            .http
            .get(&url)
            .bearer_auth(token)
            .send()
            .await
            .map_err(|e| format!("failed to reach REDLY Cloud: {e}"))?;

        if !response.status().is_success() {
            return Err(format!("agent pull failed ({})", response.status()));
        }

        response
            .json::<PullResponse>()
            .await
            .map(|r| r.agents)
            .map_err(|e| format!("unexpected response from REDLY Cloud: {e}"))
    }
}

impl Default for CloudSyncClient {
    fn default() -> Self {
        Self::new()
    }
}
