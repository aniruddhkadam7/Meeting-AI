use tauri::{AppHandle, State};

use crate::rag::EmbedProcessConfig;
use crate::state::AppState;

use super::manager::{PerformanceConfig, PerformanceMode};
use super::profile::HardwareProfile;
use super::store;
use super::tier::HardwareTier;
use super::PerformanceState;

#[derive(serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PerformanceModeInfo {
    pub mode: PerformanceMode,
    pub detected_tier: HardwareTier,
    pub effective_config: PerformanceConfig,
}

#[tauri::command]
pub fn get_hardware_profile(state: State<'_, PerformanceState>) -> Result<HardwareProfile, String> {
    let manager = state.0.lock().map_err(|e| e.to_string())?;
    Ok(manager.profile().clone())
}

#[tauri::command]
pub fn get_performance_mode(state: State<'_, PerformanceState>) -> Result<PerformanceModeInfo, String> {
    let manager = state.0.lock().map_err(|e| e.to_string())?;
    Ok(PerformanceModeInfo {
        mode: manager.mode(),
        detected_tier: manager.detected_tier(),
        effective_config: manager.effective_config(),
    })
}

/// Persists the mode, updates the in-memory manager, and restarts the local
/// RAG sidecar with the new tier's embedding config — Python's `Settings`
/// class (packages/rag/app/core/config.py) reads `RAG_EMBED_BATCH_SIZE`/
/// `RAG_TORCH_THREADS` once at process startup, so applying a new value
/// requires a fresh process (see `rag::RagServiceHandle::restart`'s doc
/// comment). This means a mode change causes a brief (roughly the same
/// window as initial app startup's RAG health-poll) interruption to local
/// document search/upload — accepted as correct, simple UX rather than
/// attempting live in-process reconfiguration.
///
/// STT thread count does NOT trigger any sidecar restart here — it takes
/// effect on the next recording session, since forcibly killing an
/// in-progress recording's STT sidecar on a settings change would be a
/// worse user experience than a stale thread count for the rest of the
/// current session. The cloud LLM/backend architecture is untouched by mode
/// changes entirely — WhitedotAI's LLM call is not hardware-tiered (see
/// `hardware::manager`'s module doc).
#[tauri::command]
pub async fn set_performance_mode(
    app: AppHandle,
    state: State<'_, AppState>,
    performance: State<'_, PerformanceState>,
    mode: PerformanceMode,
) -> Result<(), String> {
    store::save_mode(&app, mode)?;

    let embed_config = {
        let mut manager = performance.0.lock().map_err(|e| e.to_string())?;
        manager.set_mode(mode);
        let cfg = manager.effective_config();
        EmbedProcessConfig {
            embed_batch_size: cfg.rag_embed_batch_size,
            torch_threads: cfg.rag_torch_threads,
        }
    };

    // Only restart if a RAG service is actually running (venv present and
    // spawn succeeded at startup) — no-op otherwise, matching how every
    // other RAG-touching command treats an unavailable service as a
    // non-fatal "feature unavailable" state rather than an error here.
    let needs_restart = {
        let rag_slot = state.rag_service.lock().map_err(|e| e.to_string())?;
        rag_slot.is_some()
    };
    if needs_restart {
        {
            let mut rag_slot = state.rag_service.lock().map_err(|e| e.to_string())?;
            if let Some(handle) = rag_slot.as_mut() {
                handle.restart(embed_config)?;
            }
        }
        // Same reasoning as the initial startup poll in lib.rs's .setup():
        // the embedding model can take a while to load on first request
        // after a fresh process starts, so this waits before returning
        // rather than reporting success while the service is still cold.
        // A `false` return here just means RAG commands will report
        // "unavailable" until it does come up, same as at initial startup.
        // Run via spawn_blocking (not directly in this async fn) since the
        // health poll sleeps synchronously for up to ~60s — blocking that
        // long directly on this task would tie up a tokio worker thread.
        let _ = tauri::async_runtime::spawn_blocking(crate::rag::wait_until_healthy_default).await;
    }

    Ok(())
}
