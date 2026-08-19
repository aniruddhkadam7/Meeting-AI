//! Adaptive hardware-based performance tuning for WhitedotAI's local STT and RAG
//! pipelines. See docs/performance-tuning.md (once Milestone 7 lands) for
//! the benchmark evidence behind the tier→config table in `manager.rs`.
//!
//! Scope: STT (sherpa-onnx sidecar thread count) and RAG (embedding
//! batch/thread count, retrieval top_k/context/timeout) only. WhitedotAI's LLM
//! is a cloud API call via `apps/backend` — not touched here, and never
//! hardware-tiered (see `manager.rs`'s module doc on LLM context).

pub mod commands;
pub mod gpu;
pub mod manager;
pub mod pressure;
pub mod profile;
pub mod storage;
pub mod store;
pub mod stt_rag_coordination;
pub mod telemetry;
pub mod tier;

use std::sync::Mutex;

use tauri::{AppHandle, Manager};

use manager::PerformanceManager;

/// Tauri-managed state wrapping the single `PerformanceManager` instance —
/// registered directly via `.manage(...)`, following the same top-level
/// state pattern as `NotesStore`/`AgentStore`, rather than nesting inside
/// `AppState`. `Mutex`-wrapped because Tauri commands run on arbitrary
/// threads.
pub struct PerformanceState(pub Mutex<PerformanceManager>);

/// Detects hardware and loads the persisted mode preference. Called once
/// from `lib.rs`'s `.setup()`, since loading the persisted mode needs an
/// `AppHandle` (to resolve the app data directory) that isn't available at
/// `.manage()` time.
pub fn init(app: &AppHandle) -> PerformanceState {
    let profile = profile::detect();
    let mode = store::load_mode(app);
    log::info!(
        "hardware profile: {} logical cores, {}MB RAM, gpu={:?}, ssd={:?}",
        profile.cpu_logical_cores,
        profile.total_ram_mb,
        profile.gpu_name,
        profile.storage_is_ssd
    );
    let manager = PerformanceManager::new(profile, mode);
    log::info!("performance mode: {:?}, detected tier: {:?}", manager.mode(), manager.detected_tier());
    PerformanceState(Mutex::new(manager))
}

/// Convenience for spawn-time call sites (Milestones 4b/5) that just need
/// the current effective config without holding onto the manager. Does NOT
/// consult the Milestone 6 memory-pressure tracker — see
/// `effective_config_checked` for the checkpoint-driven variant that does.
pub fn effective_config(app: &AppHandle) -> manager::PerformanceConfig {
    let state = app.state::<PerformanceState>();
    let manager = state.0.lock().unwrap();
    manager.effective_config()
}

/// Milestone 6 checkpoint: feeds a freshly-measured available-RAM reading
/// into the sustained-pressure tracker and returns the (possibly clamped)
/// config to use, plus a log-worthy reason if the pressure state changed on
/// this call. Callers should measure RAM immediately before calling this
/// (see `profile::available_ram_mb`) — the natural checkpoints are STT
/// sidecar spawn and RAG document-upload/indexing start, not a timer.
pub fn effective_config_checked(app: &AppHandle) -> manager::PerformanceConfig {
    let available = profile::available_ram_mb();
    let state = app.state::<PerformanceState>();
    let mut manager = state.0.lock().unwrap();
    let (config, reason) = manager.effective_config_checked(available);
    if let Some(reason) = reason {
        log::warn!("performance: {reason}");
    }
    config
}

/// Milestone 7: reads the current performance-correlation context (tier,
/// mode, pressure state, effective config) without observing a new RAM
/// sample — safe to call from any pipeline-stage instrumentation point.
pub fn perf_context(app: &AppHandle) -> telemetry::PerfContext {
    let state = app.state::<PerformanceState>();
    let manager = state.0.lock().unwrap();
    manager.perf_context()
}

/// STT/RAG scheduling coordination (Phase B): whether active STT should
/// currently throttle RAG background indexing on this machine/mode. See
/// `manager::PerformanceManager::should_throttle_background_work` for the
/// exact per-mode rule and `stt_rag_coordination` for how this gets acted
/// on.
pub fn should_throttle_background_work(app: &AppHandle) -> bool {
    let state = app.state::<PerformanceState>();
    let manager = state.0.lock().unwrap();
    manager.should_throttle_background_work()
}

// Re-exported for the Milestone 6 runtime-adaptation checkpoint, which
// needs a fresh available-RAM reading independent of the cached profile.
pub use profile::available_ram_mb;
pub use manager::PerformanceConfig;
