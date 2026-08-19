//! Thin client for Supabase Auth's REST API (GoTrue). The desktop app talks
//! to Supabase directly for sign-in/sign-up/refresh — WhitedotAI's own FastAPI
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

/// Signup with "Confirm email" enabled on the Supabase project (the
/// documented recommendation, see supabase/README.md) returns `200 OK` with
/// a user object but `"session": null` — no access/refresh token at all,
/// since the account isn't usable until the user clicks the confirmation
/// link. `GoTrueTokenResponse` requires `access_token`, so that shape would
/// fail to deserialize and surface a confusing "unexpected response" error;
/// this narrower shape lets `sign_up` detect the case and return a clear
/// message instead.
#[derive(Debug, Deserialize)]
struct GoTrueSignupNeedsConfirmationResponse {
    #[allow(dead_code)]
    id: String,
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
                "WhitedotAI Cloud is not configured on this build (missing SUPABASE_URL/SUPABASE_ANON_KEY)"
                    .to_string(),
            );
        }
        Ok((url, key))
    }

    /// Returns `Ok(None)` when the project has "Confirm email" enabled (the
    /// documented default) and the new account has no session yet — the
    /// caller should tell the user to check their inbox rather than treat
    /// this as a failure. Returns `Ok(Some(session))` when confirmations are
    /// disabled and Supabase hands back a usable session immediately.
    pub async fn sign_up(&self, email: &str, password: &str) -> Result<Option<Session>, String> {
        let (base_url, anon_key) = self.require_configured()?;
        let response = self
            .http
            .post(format!("{base_url}/auth/v1/signup"))
            .header("apikey", &anon_key)
            .json(&serde_json::json!({ "email": email, "password": password }))
            .send()
            .await
            .map_err(|e| format!("could not reach WhitedotAI Cloud: {e}"))?;

        let status = response.status();
        let body_text = response.text().await.unwrap_or_default();

        if !status.is_success() {
            if let Ok(err) = serde_json::from_str::<GoTrueError>(&body_text) {
                return Err(err.message);
            }
            return Err(format!("sign-up failed ({status})"));
        }

        parse_signup_body(&body_text)
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
            .map_err(|e| format!("could not reach WhitedotAI Cloud: {e}"))?;

        let status = response.status();
        let body_text = response.text().await.unwrap_or_default();

        if !status.is_success() {
            if let Ok(err) = serde_json::from_str::<GoTrueError>(&body_text) {
                return Err(err.message);
            }
            return Err(format!("sign-in failed ({status})"));
        }

        let parsed: GoTrueTokenResponse =
            serde_json::from_str(&body_text).map_err(|e| format!("unexpected response from WhitedotAI Cloud: {e}"))?;

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
            .map_err(|e| format!("could not reach WhitedotAI Cloud: {e}"))?;

        let status = response.status();
        let body_text = response.text().await.unwrap_or_default();

        if !status.is_success() {
            if let Ok(err) = serde_json::from_str::<GoTrueError>(&body_text) {
                return Err(err.message);
            }
            return Err(format!("session refresh failed ({status})"));
        }

        let parsed: GoTrueTokenResponse =
            serde_json::from_str(&body_text).map_err(|e| format!("unexpected response from WhitedotAI Cloud: {e}"))?;

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

/// Parses a successful (2xx) `/auth/v1/signup` response body into either a
/// usable session (confirmations disabled) or `None` (confirmations
/// enabled — account created, no session yet). Pure and network-free so the
/// three response shapes GoTrue can return here are unit-testable directly.
fn parse_signup_body(body_text: &str) -> Result<Option<Session>, String> {
    if let Ok(parsed) = serde_json::from_str::<GoTrueTokenResponse>(body_text) {
        return Ok(Some(Session {
            access_token: parsed.access_token,
            refresh_token: parsed.refresh_token,
            user_id: parsed.user.id,
            email: parsed.user.email,
            expires_at: now_unix() + parsed.expires_in,
        }));
    }

    // No access_token in the body — "Confirm email" is on and the account
    // was created but isn't signed in yet. Confirm the response at least
    // looks like a real signup response (has a user id) before treating
    // this as the confirmation-pending case rather than some other
    // unexpected shape.
    if serde_json::from_str::<GoTrueSignupNeedsConfirmationResponse>(body_text).is_ok() {
        return Ok(None);
    }

    Err(format!("unexpected response from WhitedotAI Cloud: {body_text}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn signup_with_confirmations_disabled_returns_a_session() {
        let body = serde_json::json!({
            "access_token": "at",
            "refresh_token": "rt",
            "expires_in": 3600,
            "user": { "id": "user-1", "email": "u@example.com" }
        })
        .to_string();
        let result = parse_signup_body(&body).unwrap();
        let session = result.expect("expected a session");
        assert_eq!(session.access_token, "at");
        assert_eq!(session.user_id, "user-1");
    }

    #[test]
    fn signup_with_confirmations_enabled_returns_none_not_an_error() {
        // GoTrue's actual shape when "Confirm email" is on: a user object,
        // no access_token, session: null.
        let body = serde_json::json!({
            "id": "user-1",
            "email": "u@example.com",
            "confirmation_sent_at": "2026-01-01T00:00:00Z",
            "session": null
        })
        .to_string();
        let result = parse_signup_body(&body).unwrap();
        assert!(result.is_none());
    }

    #[test]
    fn signup_with_unrecognized_body_is_an_error_not_silently_none() {
        let body = "{}";
        let result = parse_signup_body(body);
        assert!(result.is_err());
    }
}
