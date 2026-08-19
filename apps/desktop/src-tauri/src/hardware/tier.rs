//! Hardware capability scoring: turns a `HardwareProfile` into one of four
//! tiers using a transparent, additive point system (not a black-box
//! formula) so it stays debuggable. Weighted toward CPU cores and RAM, since
//! those are what the one real measurement REDLY has (`docs/stt-benchmark.md`,
//! a 10-core/16-thread/15.6GB/RTX3050 machine) shows STT/RAG are actually
//! bound by — GPU and storage are minor tiebreaker/display signals only,
//! since GPU execution isn't wired for STT/RAG in this pass and storage type
//! only affects one-time model-load latency, not steady-state throughput.

use super::profile::HardwareProfile;

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, serde::Serialize, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum HardwareTier {
    Entry,
    Standard,
    Performance,
    HighPerformance,
}

fn cpu_points(logical_cores: usize) -> u32 {
    match logical_cores {
        16.. => 40,
        8..=15 => 28,
        4..=7 => 14,
        _ => 4,
    }
}

fn ram_points(total_ram_mb: u64) -> u32 {
    match total_ram_mb {
        m if m >= 16 * 1024 => 30,
        m if m >= 8 * 1024 => 20,
        m if m >= 4 * 1024 => 8,
        _ => 0,
    }
}

fn gpu_points(profile: &HardwareProfile) -> u32 {
    match profile.gpu_vram_mb {
        Some(vram) if vram >= 4 * 1024 => 5,
        _ => 0,
    }
}

fn storage_points(profile: &HardwareProfile) -> u32 {
    if profile.storage_is_ssd == Some(true) {
        5
    } else {
        0
    }
}

/// Additive score, max 80 (40 cores + 30 RAM + 5 GPU + 5 SSD).
pub fn score(profile: &HardwareProfile) -> u32 {
    cpu_points(profile.cpu_logical_cores)
        + ram_points(profile.total_ram_mb)
        + gpu_points(profile)
        + storage_points(profile)
}

pub fn tier_for_score(score: u32) -> HardwareTier {
    match score {
        65..=80 => HardwareTier::HighPerformance,
        45..=64 => HardwareTier::Performance,
        20..=44 => HardwareTier::Standard,
        _ => HardwareTier::Entry,
    }
}

pub fn classify(profile: &HardwareProfile) -> HardwareTier {
    tier_for_score(score(profile))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn profile(cores: usize, ram_gb: u64, vram_gb: Option<u64>, ssd: Option<bool>) -> HardwareProfile {
        HardwareProfile {
            cpu_physical_cores: cores / 2,
            cpu_logical_cores: cores,
            cpu_brand: "Test CPU".to_string(),
            total_ram_mb: ram_gb * 1024,
            available_ram_mb: ram_gb * 1024 / 2,
            gpu_vendor: vram_gb.map(|_| "NVIDIA".to_string()),
            gpu_name: vram_gb.map(|_| "Test GPU".to_string()),
            gpu_vram_mb: vram_gb.map(|g| g * 1024),
            storage_is_ssd: ssd,
            windows_version: "Windows 11".to_string(),
        }
    }

    #[test]
    fn dev_machine_like_profile_is_high_performance() {
        // Mirrors docs/stt-benchmark.md's dev machine: i5-13400 (10c/16t),
        // 15.6GB RAM (rounds down into the 8-15GB bracket), RTX 3050 8GB, SSD.
        let p = profile(16, 15, Some(8), Some(true));
        assert_eq!(classify(&p), HardwareTier::HighPerformance);
    }

    #[test]
    fn low_end_profile_is_entry() {
        // 2 cores + 4GB RAM: 4 (cpu) + 8 (ram) = 12, below the 20-point
        // Entry/Standard boundary.
        let p = profile(2, 4, None, None);
        assert_eq!(classify(&p), HardwareTier::Entry);
    }

    #[test]
    fn mid_range_profile_is_standard_or_performance() {
        let p = profile(6, 16, None, Some(true));
        let tier = classify(&p);
        assert!(tier == HardwareTier::Standard || tier == HardwareTier::Performance);
    }

    #[test]
    fn no_gpu_or_ssd_never_penalizes_below_zero() {
        let p = profile(4, 4, None, None);
        assert_eq!(score(&p), cpu_points(4) + ram_points(4096));
    }

    #[test]
    fn tier_ordering_is_monotonic_in_score() {
        assert!(HardwareTier::Entry < HardwareTier::Standard);
        assert!(HardwareTier::Standard < HardwareTier::Performance);
        assert!(HardwareTier::Performance < HardwareTier::HighPerformance);
    }
}
