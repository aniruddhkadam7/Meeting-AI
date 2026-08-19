//! On-disk persistence for the user's performance mode preference only —
//! the hardware profile itself is never persisted (re-detected fresh every
//! launch, see `profile::detect`), since hardware/available-RAM can change
//! between runs and a stale cached profile would be a correctness bug, not
//! just a nicety. Follows the same load/save-to-AppData-JSON pattern as
//! `notes_mode::store`.

use std::fs;
use std::path::PathBuf;

use tauri::{AppHandle, Manager};

use super::manager::PerformanceMode;

#[derive(serde::Serialize, serde::Deserialize)]
struct StoredPerformanceSettings {
    #[serde(default)]
    mode: PerformanceMode,
}

impl Default for StoredPerformanceSettings {
    fn default() -> Self {
        Self { mode: PerformanceMode::Adaptive }
    }
}

fn settings_file_path(app: &AppHandle) -> Result<PathBuf, String> {
    let dir = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("failed to resolve app data directory: {e}"))?;
    fs::create_dir_all(&dir).map_err(|e| format!("failed to create app data directory: {e}"))?;
    Ok(dir.join("performance.json"))
}

/// Missing file or parse failure both fall back to `Adaptive` — the safe
/// default, matching the "corrupt/missing = safe default" convention used
/// by `notes_mode::store` and `overlaySettings.ts`.
pub fn load_mode(app: &AppHandle) -> PerformanceMode {
    let path = match settings_file_path(app) {
        Ok(p) => p,
        Err(err) => {
            log::warn!("performance store: {err}");
            return PerformanceMode::Adaptive;
        }
    };
    match fs::read_to_string(&path) {
        Ok(contents) => serde_json::from_str::<StoredPerformanceSettings>(&contents)
            .map(|s| s.mode)
            .unwrap_or_default(),
        Err(_) => PerformanceMode::Adaptive,
    }
}

pub fn save_mode(app: &AppHandle, mode: PerformanceMode) -> Result<(), String> {
    let path = settings_file_path(app)?;
    let json = serde_json::to_string_pretty(&StoredPerformanceSettings { mode }).map_err(|e| e.to_string())?;
    fs::write(&path, json).map_err(|e| e.to_string())
}
