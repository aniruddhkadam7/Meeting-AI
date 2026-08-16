//! Thin client for Supabase Auth's REST API (GoTrue). The desktop app talks
//! to Supabase directly for sign-in/sign-up/refresh — REDLY's own FastAPI
//! backend never sees a password, it only ever verifies the resulting JWT
//! (see apps/backend/app/core/auth.py).

use std::time::Duration;

use serde::Deserialize;

use super::config::{supabase_anon_key, supabase_url};
use super::session_store::Session;

pub struct SupabaseAuthClient {
    http: reqwest::Client,
}

#[derive(Debug, Deserialize)]
struct GoTrueTokenResponse {
    access_token: String,
    refresh_token: String,
    expires_in: i64,
    user: GoTrueUser,
}

#[derive(Debug, Deserialize)]
struct GoTrueUser {
    id: String,
    email: Option<String>,
}

#[derive(Debug, Deserialize)]
struct GoTrueError {
    #[serde(alias = "error_description", alias = "msg")]
    message: String,
}

impl SupabaseAuthClient {
    pub fn new() -> Self {
        crate::tls_init::ensure_installed();
        Self {
            http: reqwest::Client::builder()
                .timeout(Duration::from_secs(15))
                .build()
                .unwrap_or_default(),
        }
    }

    fn require_configured(&self) -> Result<(String, String), String> {
        let url = supabase_url();
        let key = supabase_anon_key();
        if url.is_empty() || key.is_empty() {
            return Err(
                "REDLY Cloud is not configured on this build (missing SUPABASE_URL/SUPABASE_ANON_KEY)"
                    .to_string(),
            );
        }
        Ok((url, key))
    }

    pub async fn sign_up(&self, email: &str, password: &str) -> Result<Session, String> {
        let (base_url, anon_key) = self.require_configured()?;
        self.token_request(&format!("{base_url}/auth/v1/signup"), &anon_key, email, password)
            .await
    }

    pub async fn sign_in(&self, email: &str, password: &str) -> Result<Session, String> {
        let (base_url, anon_key) = self.require_configured()?;
        self.token_request(
            &format!("{base_url}/auth/v1/token?grant_type=password"),
            &anon_key,
            email,
            password,
        )
        .await
    }

    async fn token_request(
        &self,
        url: &str,
        anon_key: &str,
        email: &str,
        password: &str,
    ) -> Result<Session, String> {
        let response = self
            .http
            .post(url)
            .header("apikey", anon_key)
            .json(&serde_json::json!({ "email": email, "password": password }))
            .send()
            .await
            .map_err(|e| format!("could not reach REDLY Cloud: {e}"))?;

        let status = response.status();
        let body_text = response.text().await.unwrap_or_default();

        if !status.is_success() {
            if let Ok(err) = serde_json::from_str::<GoTrueError>(&body_text) {
                return Err(err.message);
            }
            return Err(format!("sign-in failed ({status})"));
        }

        let parsed: GoTrueTokenResponse =
            serde_json::from_str(&body_text).map_err(|e| format!("unexpected response from REDLY Cloud: {e}"))?;

        Ok(Session {
            access_token: parsed.access_token,
            refresh_token: parsed.refresh_token,
            user_id: parsed.user.id,
            email: parsed.user.email,
            expires_at: now_unix() + parsed.expires_in,
        })
    }

    /// Refreshes an expiring session using its refresh token. Called
    /// lazily by callers before a cloud request if the stored session's
    /// `expires_at` is close, rather than on a background timer.
    pub async fn refresh(&self, refresh_token: &str) -> Result<Session, String> {
        let (base_url, anon_key) = self.require_configured()?;
        let response = self
            .http
            .post(format!("{base_url}/auth/v1/token?grant_type=refresh_token"))
            .header("apikey", &anon_key)
            .json(&serde_json::json!({ "refresh_token": refresh_token }))
            .send()
            .await
            .map_err(|e| format!("could not reach REDLY Cloud: {e}"))?;

        let status = response.status();
        let body_text = response.text().await.unwrap_or_default();

        if !status.is_success() {
            if let Ok(err) = serde_json::from_str::<GoTrueError>(&body_text) {
                return Err(err.message);
            }
            return Err(format!("session refresh failed ({status})"));
        }

        let parsed: GoTrueTokenResponse =
            serde_json::from_str(&body_text).map_err(|e| format!("unexpected response from REDLY Cloud: {e}"))?;

        Ok(Session {
            access_token: parsed.access_token,
            refresh_token: parsed.refresh_token,
            user_id: parsed.user.id,
            email: parsed.user.email,
            expires_at: now_unix() + parsed.expires_in,
        })
    }
}

impl Default for SupabaseAuthClient {
    fn default() -> Self {
        Self::new()
    }
}

fn now_unix() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0)
}
