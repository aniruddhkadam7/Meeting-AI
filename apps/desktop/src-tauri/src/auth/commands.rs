use super::client::SupabaseAuthClient;
use super::config::is_configured;
use super::session_store::{self, Session};

#[derive(Debug, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SessionInfo {
    pub user_id: String,
    pub email: Option<String>,
}

impl From<&Session> for SessionInfo {
    fn from(s: &Session) -> Self {
        Self {
            user_id: s.user_id.clone(),
            email: s.email.clone(),
        }
    }
}

/// Discriminated result for sign-up so the frontend can tell "you're signed
/// in" apart from "check your email" without parsing an error string —
/// both are successful outcomes of sign-up, not failures.
#[derive(Debug, serde::Serialize)]
#[serde(tag = "status", rename_all = "camelCase")]
pub enum SignUpResult {
    SignedIn { session: SessionInfo },
    ConfirmationRequired,
}

#[tauri::command]
pub fn auth_cloud_configured() -> bool {
    is_configured()
}

#[tauri::command]
pub async fn auth_sign_up(email: String, password: String) -> Result<SignUpResult, String> {
    match SupabaseAuthClient::new().sign_up(&email, &password).await? {
        Some(session) => {
            let info = SessionInfo::from(&session);
            session_store::store_session(&session)?;
            Ok(SignUpResult::SignedIn { session: info })
        }
        None => Ok(SignUpResult::ConfirmationRequired),
    }
}

#[tauri::command]
pub async fn auth_sign_in(email: String, password: String) -> Result<SessionInfo, String> {
    let session = SupabaseAuthClient::new().sign_in(&email, &password).await?;
    let info = SessionInfo::from(&session);
    session_store::store_session(&session)?;
    Ok(info)
}

#[tauri::command]
pub fn auth_sign_out() -> Result<(), String> {
    session_store::clear_session()
}

/// Returns the currently signed-in user, if any, without making a network
/// call — reads whatever is in the credential store as-is. Callers that need
/// a guaranteed-fresh token for an actual API call should use
/// `super::get_valid_access_token` instead (Rust-internal only, not exposed
/// as a Tauri command since the frontend never needs the raw token).
#[tauri::command]
pub fn auth_get_session() -> Result<Option<SessionInfo>, String> {
    Ok(session_store::load_session()?.as_ref().map(SessionInfo::from))
}
