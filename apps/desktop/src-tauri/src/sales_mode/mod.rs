//! Sales Mode: a frameless, always-on-top overlay window for live customer
//! calls — speaker-separated transcript, live suggested talking points, and
//! tracked requirements/objections/commitments, ending in an AI call summary
//! archived to Sales history.
//!
//! Mirrors `interview_mode`'s window/command split, but built on the shared
//! `overlay_window` module (parameterized by label) rather than Interview
//! Mode's own window module, which stays untouched.

pub mod commands;
pub mod history;

pub const SALES_OVERLAY_LABEL: &str = "sales-overlay";
