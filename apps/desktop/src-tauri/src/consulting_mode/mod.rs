//! Consulting Mode: a frameless, always-on-top overlay window for live
//! client engagement sessions — speaker-separated transcript, suggested
//! structured questions/recommendations, and tracked risks/assumptions/
//! decisions/dependencies/action items, ending in structured session notes
//! archived (per-engagement) to Consulting history.

pub mod commands;
pub mod history;

pub const CONSULTING_OVERLAY_LABEL: &str = "consulting-overlay";
