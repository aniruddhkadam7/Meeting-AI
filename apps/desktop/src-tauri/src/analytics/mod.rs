//! Lightweight, privacy-conscious product analytics.
//!
//! Events are queued in memory and flushed to REDLY Cloud's
//! `/api/v1/analytics/events` in small batches, only when the user is
//! signed in — analytics is opt-in by virtue of being tied to having an
//! account, exactly like agent sync. Never queues raw audio, document
//! content, or full transcript/message text; every call site here passes a
//! small, deliberately-named property bag (see `track` call sites in
//! `commands.rs`/mode modules), not arbitrary payloads.
//!
//! Flush failures (offline, not signed in, cloud not configured) are
//! logged and the queue is simply retried on the next flush — analytics
//! must never block or fail a real user action.

mod client;
mod queue;

pub use queue::{flush_events, track, AnalyticsQueue};
