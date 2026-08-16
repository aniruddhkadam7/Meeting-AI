use std::time::Duration;

use serde::Serialize;

use crate::backend::backend_url;

#[derive(Debug, Clone, Serialize)]
pub struct AnalyticsEvent {
    pub event_name: String,
    pub properties: serde_json::Value,
    pub app_version: String,
}

#[derive(Serialize)]
struct Batch<'a> {
    events: &'a [AnalyticsEvent],
}

pub struct AnalyticsClient {
    http: reqwest::Client,
    base_url: String,
}

impl AnalyticsClient {
    pub fn new() -> Self {
        crate::tls_init::ensure_installed();
        Self {
            http: reqwest::Client::builder()
                .timeout(Duration::from_secs(10))
                .build()
                .unwrap_or_default(),
            base_url: backend_url(),
        }
    }

    pub async fn send_batch(&self, token: &str, events: &[AnalyticsEvent]) -> Result<(), String> {
        if events.is_empty() {
            return Ok(());
        }
        let url = format!("{}/api/v1/analytics/events", self.base_url);
        let response = self
            .http
            .post(&url)
            .bearer_auth(token)
            .json(&Batch { events })
            .send()
            .await
            .map_err(|e| format!("failed to reach REDLY Cloud: {e}"))?;

        if response.status().is_success() {
            Ok(())
        } else {
            Err(format!("analytics ingest failed ({})", response.status()))
        }
    }
}

impl Default for AnalyticsClient {
    fn default() -> Self {
        Self::new()
    }
}
