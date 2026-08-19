//! Runtime memory-pressure adaptation: a conservative, evidence-gated
//! overlay on top of the hardware-detected tier (`tier.rs`/`manager.rs`).
//!
//! Goal (per explicit product decision): prevent a low-memory system from
//! becoming unresponsive — NOT continuously re-tune settings. This is
//! deliberately narrow in scope:
//!
//! - Only ever *reduces* local workload (STT thread count for the next
//!   recording session, RAG retrieval top_k/context budget/timeout for the
//!   next question) below what the detected tier/user mode would otherwise
//!   select. It never increases beyond the tier/mode's own config.
//! - Never touches RAG's embedding batch size / torch thread count — those
//!   are fixed at RAG-sidecar-process-spawn time (see `manager.rs`'s module
//!   doc and `rag::process::RagServiceHandle::spawn`'s doc comment), and
//!   restarting that process is a deliberate, user-initiated action
//!   (`set_performance_mode`), never an automatic side effect of a memory
//!   reading. This module holds no reference to `RagServiceHandle` at all.
//! - Never changes STT model choice, VAD, endpointing, or anything on the
//!   cloud LLM/backend path — those are out of scope for hardware-adaptive
//!   tuning entirely (see `manager.rs`'s module doc).
//! - Judges "pressure" from sustained readings, not one instantaneous
//!   sample, and applies hysteresis so entering and exiting pressure state
//!   both require the signal to hold for a while — see `PressureTracker`'s
//!   doc comment for the exact rule.
//!
//! This is checkpoint-driven (sampled when a caller asks, e.g. before
//! spawning an STT sidecar or planning a RAG retrieval), not a continuous
//! background poll — no timer thread, no periodic wakeups. A checkpoint
//! that never fires (the app sits idle) simply never re-evaluates, which is
//! correct: there is nothing to protect if nothing is about to consume
//! memory.

use std::time::{Duration, Instant};

use super::manager::PerformanceConfig;
use super::tier::HardwareTier;

/// Available RAM below this is treated as a candidate pressure signal.
/// Anchored to STT's own measured footprint (228MB, see
/// docs/stt-benchmark.md) — 1024MB is roughly 4x that, leaving headroom for
/// RAG's embedding model (~90MB weights + torch/transformers overhead) and
/// the OS/webview on top, without being so tight that ordinary memory
/// fluctuation from an unrelated application falsely triggers it.
const LOW_MEMORY_THRESHOLD_MB: u64 = 1024;

/// A single low reading is not "sustained" — require at least this many
/// consecutive checkpoint samples below the threshold before entering
/// pressure state. Two, not one: the smallest number that distinguishes
/// "briefly dipped, already recovering" from "still low next time we
/// checked," without requiring a long observation window that would delay
/// protecting a genuinely struggling machine.
const CONSECUTIVE_LOW_SAMPLES_TO_ENTER: u32 = 2;

/// Once in pressure state, available RAM must read comfortably above the
/// threshold (with margin, see `RECOVERY_MARGIN_MB`) for at least this long
/// before restoring normal config — the cooldown. Prevents flapping back
/// and forth if memory hovers right at the threshold (e.g. another
/// application's own working set oscillating). 90s is long enough to ride
/// out a brief recovery blip, short enough that a genuine, sustained
/// recovery (the other application closing, a one-time spike passing)
/// isn't stuck in reduced mode for an unreasonable stretch of a session.
const COOLDOWN: Duration = Duration::from_secs(90);

/// Recovery must clear the threshold by more than just returning to
/// exactly the trigger point — a small margin (not just `> THRESHOLD`)
/// avoids a value sitting right at the boundary from repeatedly crossing
/// it in both directions as ordinary noise.
const RECOVERY_MARGIN_MB: u64 = 256;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PressureState {
    Normal,
    UnderPressure,
}

/// Tracks sustained memory pressure across checkpoint samples and decides,
/// with hysteresis, when to enter/exit a reduced-workload state.
///
/// State machine:
///
/// ```text
/// Normal --(N consecutive low samples)--> UnderPressure
/// UnderPressure --(available RAM > threshold+margin for >= COOLDOWN)--> Normal
/// ```
///
/// A sample outside the "comfortably recovered" band while under pressure
/// resets the cooldown clock (the recovery timer only counts *continuous*
/// time spent above the recovery line) — a single good reading followed by
/// a bad one does not restore normal config.
pub struct PressureTracker {
    state: PressureState,
    consecutive_low_samples: u32,
    /// When the most recent continuous stretch of "comfortably recovered"
    /// readings began, if we're currently in one. `None` means the last
    /// sample was NOT comfortably recovered (at or below threshold+margin),
    /// so there is no active recovery stretch to measure a cooldown against.
    recovery_since: Option<Instant>,
    last_sample_mb: Option<u64>,
}

impl Default for PressureTracker {
    fn default() -> Self {
        Self {
            state: PressureState::Normal,
            consecutive_low_samples: 0,
            recovery_since: None,
            last_sample_mb: None,
        }
    }
}

impl PressureTracker {
    pub fn state(&self) -> PressureState {
        self.state
    }

    /// Feeds one fresh available-RAM reading in and returns `Some(reason)`
    /// if the state changed (for the caller to log), `None` if it didn't.
    /// Callers should call this at a natural checkpoint (session/job start)
    /// with a freshly-measured `available_ram_mb`, not on a timer.
    pub fn observe(&mut self, available_ram_mb: u64, now: Instant) -> Option<String> {
        self.last_sample_mb = Some(available_ram_mb);

        match self.state {
            PressureState::Normal => {
                if available_ram_mb < LOW_MEMORY_THRESHOLD_MB {
                    self.consecutive_low_samples += 1;
                } else {
                    self.consecutive_low_samples = 0;
                }

                if self.consecutive_low_samples >= CONSECUTIVE_LOW_SAMPLES_TO_ENTER {
                    self.state = PressureState::UnderPressure;
                    self.recovery_since = None;
                    let reason = format!(
                        "entering reduced-workload mode: available RAM {available_ram_mb}MB stayed below {LOW_MEMORY_THRESHOLD_MB}MB for {} consecutive checks",
                        self.consecutive_low_samples
                    );
                    return Some(reason);
                }
                None
            }
            PressureState::UnderPressure => {
                let recovery_line = LOW_MEMORY_THRESHOLD_MB + RECOVERY_MARGIN_MB;
                if available_ram_mb > recovery_line {
                    let since = self.recovery_since.get_or_insert(now);
                    let recovered_for = now.duration_since(*since);
                    if recovered_for >= COOLDOWN {
                        self.state = PressureState::Normal;
                        self.consecutive_low_samples = 0;
                        self.recovery_since = None;
                        let reason = format!(
                            "restoring normal performance mode: available RAM stayed above {recovery_line}MB for {:.0}s (>= {}s cooldown)",
                            recovered_for.as_secs_f64(),
                            COOLDOWN.as_secs()
                        );
                        return Some(reason);
                    }
                } else {
                    // Dropped back at/below the recovery line — the
                    // continuous "recovered" stretch is broken, so the
                    // cooldown timer resets (does not restore normal mode
                    // just because SOME earlier sample was briefly good).
                    self.recovery_since = None;
                }
                None
            }
        }
    }

    /// Applies this tracker's current state to a tier-selected config,
    /// producing the config that should actually be used. `Normal` is a
    /// pure passthrough. `UnderPressure` clamps STT threads and RAG
    /// retrieval budget down to the ENTRY tier's values (never below what
    /// ENTRY already uses — pressure adaptation is a ceiling, not its own
    /// separate scale) while leaving `rag_embed_batch_size`/
    /// `rag_torch_threads` completely untouched, since those cannot be
    /// changed without restarting the RAG process, which this module never
    /// does (see module doc).
    pub fn apply(&self, base: PerformanceConfig) -> PerformanceConfig {
        match self.state {
            PressureState::Normal => base,
            PressureState::UnderPressure => {
                let entry = super::manager::config_for_tier(HardwareTier::Entry, 1);
                PerformanceConfig {
                    stt_num_threads: base.stt_num_threads.min(entry.stt_num_threads),
                    rag_top_k: base.rag_top_k.min(entry.rag_top_k),
                    rag_max_context_chars: base.rag_max_context_chars.min(entry.rag_max_context_chars),
                    rag_similarity_threshold: base.rag_similarity_threshold.max(entry.rag_similarity_threshold),
                    rag_retrieval_timeout_ms: base.rag_retrieval_timeout_ms.min(entry.rag_retrieval_timeout_ms),
                    // Untouched — see doc comment above.
                    rag_embed_batch_size: base.rag_embed_batch_size,
                    rag_torch_threads: base.rag_torch_threads,
                }
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn t(seconds_from_epoch_ish: u64) -> Instant {
        // Tests only ever compare durations between two `Instant`s produced
        // by this helper, never against wall-clock time, so an arbitrary
        // fixed base plus an offset is a valid, deterministic stand-in for
        // "time passing" without sleeping in the test.
        Instant::now() + Duration::from_secs(seconds_from_epoch_ish)
    }

    // -- entering pressure: sustained, not a single blip --------------------

    #[test]
    fn a_single_low_reading_does_not_trigger_pressure() {
        let mut tracker = PressureTracker::default();
        let changed = tracker.observe(500, t(0));
        assert!(changed.is_none());
        assert_eq!(tracker.state(), PressureState::Normal);
    }

    #[test]
    fn two_consecutive_low_readings_trigger_pressure() {
        let mut tracker = PressureTracker::default();
        assert!(tracker.observe(500, t(0)).is_none());
        let changed = tracker.observe(400, t(10));
        assert!(changed.is_some());
        assert_eq!(tracker.state(), PressureState::UnderPressure);
    }

    #[test]
    fn a_low_reading_followed_by_a_healthy_one_resets_the_low_streak() {
        let mut tracker = PressureTracker::default();
        assert!(tracker.observe(500, t(0)).is_none()); // 1 low
        assert!(tracker.observe(4000, t(10)).is_none()); // healthy — resets streak
        assert!(tracker.observe(500, t(20)).is_none()); // 1 low again, not 2 in a row
        assert_eq!(tracker.state(), PressureState::Normal);
    }

    #[test]
    fn logged_reason_names_the_actual_reading_and_threshold() {
        let mut tracker = PressureTracker::default();
        tracker.observe(500, t(0));
        let reason = tracker.observe(300, t(10)).expect("should have entered pressure");
        assert!(reason.contains("300MB"));
        assert!(reason.contains("1024MB"));
    }

    // -- staying under pressure without oscillating --------------------------

    #[test]
    fn a_reading_right_at_the_threshold_does_not_recover() {
        let mut tracker = PressureTracker::default();
        tracker.observe(500, t(0));
        tracker.observe(500, t(10));
        assert_eq!(tracker.state(), PressureState::UnderPressure);
        // Exactly at LOW_MEMORY_THRESHOLD_MB, not above the recovery
        // margin — must not restore.
        let changed = tracker.observe(LOW_MEMORY_THRESHOLD_MB, t(200));
        assert!(changed.is_none());
        assert_eq!(tracker.state(), PressureState::UnderPressure);
    }

    #[test]
    fn crossing_above_threshold_but_not_the_recovery_margin_does_not_recover() {
        let mut tracker = PressureTracker::default();
        tracker.observe(500, t(0));
        tracker.observe(500, t(10));
        // Above LOW_MEMORY_THRESHOLD_MB (1024) but not above
        // threshold+margin (1280) — must not start/complete recovery.
        let changed = tracker.observe(1100, t(200));
        assert!(changed.is_none());
        assert_eq!(tracker.state(), PressureState::UnderPressure);
    }

    #[test]
    fn recovery_reading_before_cooldown_elapses_does_not_restore() {
        let mut tracker = PressureTracker::default();
        tracker.observe(500, t(0));
        tracker.observe(500, t(10));
        assert_eq!(tracker.state(), PressureState::UnderPressure);
        // Comfortably above the recovery line, but only 30s in — cooldown
        // is 90s.
        let changed = tracker.observe(4000, t(40));
        assert!(changed.is_none());
        assert_eq!(tracker.state(), PressureState::UnderPressure);
    }

    #[test]
    fn sustained_recovery_for_the_full_cooldown_restores_normal_mode() {
        let mut tracker = PressureTracker::default();
        tracker.observe(500, t(0));
        tracker.observe(500, t(10));
        assert_eq!(tracker.state(), PressureState::UnderPressure);
        tracker.observe(4000, t(20)); // recovery stretch begins here
        let changed = tracker.observe(4000, t(20 + 90)); // >= 90s later
        assert!(changed.is_some());
        assert_eq!(tracker.state(), PressureState::Normal);
    }

    #[test]
    fn a_dip_back_below_the_recovery_line_resets_the_cooldown_clock() {
        let mut tracker = PressureTracker::default();
        tracker.observe(500, t(0));
        tracker.observe(500, t(10));
        tracker.observe(4000, t(20)); // recovery stretch begins
        tracker.observe(4000, t(60)); // 40s into recovery, still under 90s cooldown
        // Dips back down — breaks the continuous recovery stretch.
        tracker.observe(1100, t(70));
        assert_eq!(tracker.state(), PressureState::UnderPressure);
        // Even though 90s has now passed since the FIRST recovery reading
        // (t=20 -> t=115 would be >=90s), the dip at t=70 reset the clock,
        // so this must NOT have recovered yet.
        let changed = tracker.observe(4000, t(115));
        assert!(changed.is_none(), "a broken recovery stretch must not count toward cooldown");
        assert_eq!(tracker.state(), PressureState::UnderPressure);
        // But continuing to recover from t=115 for the full cooldown does
        // eventually restore.
        let changed = tracker.observe(4000, t(115 + 90));
        assert!(changed.is_some());
        assert_eq!(tracker.state(), PressureState::Normal);
    }

    #[test]
    fn after_restoring_normal_mode_pressure_can_trigger_again() {
        let mut tracker = PressureTracker::default();
        tracker.observe(500, t(0));
        tracker.observe(500, t(10));
        tracker.observe(4000, t(20));
        tracker.observe(4000, t(20 + 90));
        assert_eq!(tracker.state(), PressureState::Normal);

        // A fresh sustained-low episode later in the same session.
        tracker.observe(500, t(1000));
        let changed = tracker.observe(500, t(1010));
        assert!(changed.is_some());
        assert_eq!(tracker.state(), PressureState::UnderPressure);
    }

    // -- applying pressure to config: STT/RAG-retrieval only, never embed ---

    fn sample_high_performance_config() -> PerformanceConfig {
        super::super::manager::config_for_tier(HardwareTier::HighPerformance, 16)
    }

    #[test]
    fn normal_state_passes_the_base_config_through_unchanged() {
        let tracker = PressureTracker::default();
        let base = sample_high_performance_config();
        let applied = tracker.apply(base.clone());
        assert_eq!(applied.stt_num_threads, base.stt_num_threads);
        assert_eq!(applied.rag_embed_batch_size, base.rag_embed_batch_size);
        assert_eq!(applied.rag_torch_threads, base.rag_torch_threads);
    }

    #[test]
    fn under_pressure_clamps_stt_threads_and_retrieval_budget_to_entry_tier() {
        let mut tracker = PressureTracker::default();
        tracker.observe(500, t(0));
        tracker.observe(500, t(10));
        assert_eq!(tracker.state(), PressureState::UnderPressure);

        let base = sample_high_performance_config(); // stt_num_threads=4, rag_top_k=5, etc.
        let applied = tracker.apply(base);
        let entry = super::super::manager::config_for_tier(HardwareTier::Entry, 1);

        assert_eq!(applied.stt_num_threads, entry.stt_num_threads);
        assert_eq!(applied.rag_top_k, entry.rag_top_k);
        assert_eq!(applied.rag_max_context_chars, entry.rag_max_context_chars);
        assert_eq!(applied.rag_retrieval_timeout_ms, entry.rag_retrieval_timeout_ms);
    }

    #[test]
    fn under_pressure_never_touches_rag_embed_batch_size_or_torch_threads() {
        // Regression guard for the explicit product decision: pressure
        // adaptation must never imply a RAG process restart.
        let mut tracker = PressureTracker::default();
        tracker.observe(500, t(0));
        tracker.observe(500, t(10));

        let base = sample_high_performance_config();
        let applied = tracker.apply(base.clone());
        assert_eq!(applied.rag_embed_batch_size, base.rag_embed_batch_size);
        assert_eq!(applied.rag_torch_threads, base.rag_torch_threads);
    }

    #[test]
    fn under_pressure_never_increases_a_config_that_was_already_more_conservative_than_entry() {
        // If the base config (e.g. the user is already on Battery Saver /
        // Entry tier) is already at or below Entry's values, applying
        // pressure must not raise it back up — `.min`/`.max` as used in
        // `apply` are a ceiling/floor, not a forced overwrite.
        let mut tracker = PressureTracker::default();
        tracker.observe(500, t(0));
        tracker.observe(500, t(10));

        let already_minimal = super::super::manager::config_for_tier(HardwareTier::Entry, 1);
        let applied = tracker.apply(already_minimal.clone());
        assert_eq!(applied.stt_num_threads, already_minimal.stt_num_threads);
        assert_eq!(applied.rag_top_k, already_minimal.rag_top_k);
    }
}
