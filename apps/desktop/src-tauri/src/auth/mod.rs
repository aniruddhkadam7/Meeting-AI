//! WhitedotAI Cloud authentication: signs a user in directly against Supabase
//! Auth (no WhitedotAI-run auth server), stores the resulting session in Windows
//! Credential Manager, and exposes the current access token to other modules
//! (agent sync, analytics) that need to call the FastAPI backend as an
//! authenticated user.
//!
//! The desktop app only ever holds the Supabase **anon key** (safe to embed
//! — RLS is what actually protects data, see supabase/README.md) and the
//! **user's own** access/refresh tokens after they sign in. It never holds
//! the service-role key.

mod client;
pub mod commands;
mod config;
mod session_store;

pub use client::SupabaseAuthClient;
pub use config::is_configured;
use session_store::{load_session, store_session};

/// Returns a still-valid access token for calling WhitedotAI Cloud, refreshing
/// the stored session first if it's within 60 seconds of expiring. Returns
/// `Ok(None)` if the user isn't signed in — callers (agent sync, analytics)
/// treat that as "skip this sync, cloud features are opt-in," never as an
/// error to surface to the user.
pub async fn get_valid_access_token() -> Result<Option<String>, String> {
    let Some(session) = load_session()? else {
        return Ok(None);
    };

    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_secs() as i64)
        .unwrap_or(0);

    if session.expires_at - now > 60 {
        return Ok(Some(session.access_token));
    }

    let refreshed = SupabaseAuthClient::new().refresh(&session.refresh_token).await?;
    let token = refreshed.access_token.clone();
    store_session(&refreshed)?;
    Ok(Some(token))
}
