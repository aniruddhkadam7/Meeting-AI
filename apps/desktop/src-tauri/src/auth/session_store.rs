//! Persists the Supabase session (access + refresh token) in Windows
//! Credential Manager via the `keyring` crate, so the user stays signed in
//! across app restarts without REDLY ever writing a token to a plaintext
//! file on disk.

use serde::{Deserialize, Serialize};

const SERVICE_NAME: &str = "REDLY";
const ENTRY_NAME: &str = "supabase-session";

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct Session {
    pub access_token: String,
    pub refresh_token: String,
    pub user_id: String,
    pub email: Option<String>,
    /// Unix seconds. Used by callers to decide whether to refresh before
    /// making a call, not enforced here.
    pub expires_at: i64,
}

fn entry() -> Result<keyring::Entry, String> {
    keyring::Entry::new(SERVICE_NAME, ENTRY_NAME).map_err(|e| format!("credential store unavailable: {e}"))
}

pub fn store_session(session: &Session) -> Result<(), String> {
    let json = serde_json::to_string(session).map_err(|e| e.to_string())?;
    entry()?.set_password(&json).map_err(|e| format!("failed to store session: {e}"))
}

/// Returns `Ok(None)` (not an error) if no session is stored yet — the
/// normal "signed out" state, not a failure.
pub fn load_session() -> Result<Option<Session>, String> {
    match entry()?.get_password() {
        Ok(json) => serde_json::from_str(&json)
            .map(Some)
            .map_err(|e| format!("stored session is corrupt: {e}")),
        Err(keyring::Error::NoEntry) => Ok(None),
        Err(e) => Err(format!("failed to read session: {e}")),
    }
}

pub fn clear_session() -> Result<(), String> {
    match entry()?.delete_credential() {
        Ok(()) | Err(keyring::Error::NoEntry) => Ok(()),
        Err(e) => Err(format!("failed to clear session: {e}")),
    }
}
