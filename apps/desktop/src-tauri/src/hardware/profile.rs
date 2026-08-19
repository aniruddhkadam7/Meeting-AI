//! Point-in-time snapshot of the machine WhitedotAI is running on. Detected fresh
//! at every app launch (see `manager::PerformanceManager::detect_and_load`)
//! rather than cached across launches, since hardware/available-RAM can
//! change between runs (e.g. a laptop plugged into a dock, a VM resize).

use sysinfo::System;

use super::gpu;
use super::storage;

#[derive(Debug, Clone, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct HardwareProfile {
    pub cpu_physical_cores: usize,
    pub cpu_logical_cores: usize,
    pub cpu_brand: String,
    pub total_ram_mb: u64,
    pub available_ram_mb: u64,
    pub gpu_vendor: Option<String>,
    pub gpu_name: Option<String>,
    pub gpu_vram_mb: Option<u64>,
    /// `None` means undetermined (the seek-penalty query failed or the OS
    /// denied access) — treated as "unknown", never penalized in scoring.
    pub storage_is_ssd: Option<bool>,
    pub windows_version: String,
}

/// Runs CPU/RAM/GPU/storage detection. Each sub-check is independently
/// best-effort — a GPU or storage detection failure never prevents the rest
/// of the profile from being produced, since this data only ever feeds a
/// tuning decision, not a hard requirement to start the app.
pub fn detect() -> HardwareProfile {
    let mut sys = System::new_all();
    sys.refresh_all();

    let cpu_logical_cores = sys.cpus().len().max(1);
    let cpu_physical_cores = sys.physical_core_count().unwrap_or(cpu_logical_cores).max(1);
    let cpu_brand = sys
        .cpus()
        .first()
        .map(|c| c.brand().trim().to_string())
        .filter(|s| !s.is_empty())
        .unwrap_or_else(|| "Unknown CPU".to_string());

    // sysinfo reports memory in bytes.
    let total_ram_mb = sys.total_memory() / (1024 * 1024);
    let available_ram_mb = sys.available_memory() / (1024 * 1024);

    let windows_version = System::long_os_version().unwrap_or_else(|| "Windows".to_string());

    let gpu = gpu::detect_primary_adapter();
    let storage_is_ssd = storage::detect_system_drive_is_ssd();

    HardwareProfile {
        cpu_physical_cores,
        cpu_logical_cores,
        cpu_brand,
        total_ram_mb,
        available_ram_mb,
        gpu_vendor: gpu.as_ref().map(|g| g.vendor.clone()),
        gpu_name: gpu.as_ref().map(|g| g.name.clone()),
        gpu_vram_mb: gpu.as_ref().and_then(|g| g.vram_mb),
        storage_is_ssd,
        windows_version,
    }
}

/// Snapshot of just the number that matters for the Milestone 6 runtime
/// checkpoint (spawn-time RAM check) — cheaper than a full `detect()` since
/// it skips GPU/storage/CPU-brand queries that don't change between a
/// session's checkpoints.
pub fn available_ram_mb() -> u64 {
    let mut sys = System::new();
    sys.refresh_memory();
    sys.available_memory() / (1024 * 1024)
}
