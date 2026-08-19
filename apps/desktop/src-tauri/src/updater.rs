//! Thin wrapper around `tauri-plugin-updater` so the frontend can check for
//! and apply updates with two simple commands, instead of dealing with the
//! plugin's JS API shape directly. The actual update artifact is fetched
//! from and verified against the Ed25519 public key baked into
//! `tauri.conf.json` (`plugins.updater.pubkey`) — Tauri's updater refuses to
//! install anything not signed by the matching private key, so a compromised
//! or spoofed update endpoint cannot push arbitrary code.

use serde::Serialize;
use tauri::AppHandle;
use tauri_plugin_updater::UpdaterExt;

#[derive(Debug, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct UpdateInfo {
    pub version: String,
    pub notes: Option<String>,
}

/// Checks the configured update endpoint. Returns `None` if already on the
/// latest version — never treated as an error, since "no update available"
/// is the normal steady state, not a failure.
#[tauri::command]
pub async fn check_for_update(app: AppHandle) -> Result<Option<UpdateInfo>, String> {
    let updater = app.updater().map_err(|e| format!("updater unavailable: {e}"))?;
    match updater.check().await {
        Ok(Some(update)) => Ok(Some(UpdateInfo {
            version: update.version,
            notes: update.body,
        })),
        Ok(None) => Ok(None),
        Err(e) => Err(format!("update check failed: {e}")),
    }
}

/// Downloads and installs the pending update, then relaunches the app. Only
/// ever called after the user explicitly confirms in the UI — WhitedotAI does
/// not silently self-update mid-session without the user's awareness, even
/// though the check itself runs automatically on launch.
#[tauri::command]
pub async fn install_update_and_restart(app: AppHandle) -> Result<(), String> {
    let updater = app.updater().map_err(|e| format!("updater unavailable: {e}"))?;
    let update = updater
        .check()
        .await
        .map_err(|e| format!("update check failed: {e}"))?
        .ok_or_else(|| "no update available".to_string())?;

    update
        .download_and_install(|_chunk, _total| {}, || {})
        .await
        .map_err(|e| format!("update install failed: {e}"))?;

    app.restart();
}
