use std::sync::Mutex;

use super::client::{AnalyticsClient, AnalyticsEvent};
use crate::auth;

/// In-memory event queue, capped so a runaway call site can't unboundedly
/// grow memory — old events are dropped (not the newest ones) if the cap is
/// hit, since a gap in analytics history is a far smaller problem than
/// unbounded growth in a long-running desktop process.
const MAX_QUEUED_EVENTS: usize = 500;

#[derive(Default)]
pub struct AnalyticsQueue(pub Mutex<Vec<AnalyticsEvent>>);

/// Queues one event for the next flush. Call sites pass a small, named
/// property bag — never raw audio, document text, or transcript/message
/// content. `properties` should be built with `serde_json::json!` at the
/// call site so it's obvious at a glance what's being sent.
pub fn track(queue: &AnalyticsQueue, event_name: &str, properties: serde_json::Value) {
    let mut guard = match queue.0.lock() {
        Ok(g) => g,
        Err(_) => return,
    };
    if guard.len() >= MAX_QUEUED_EVENTS {
        guard.remove(0);
    }
    guard.push(AnalyticsEvent {
        event_name: event_name.to_string(),
        properties,
        app_version: env!("CARGO_PKG_VERSION").to_string(),
    });
}

/// Drains the queue and sends it to REDLY Cloud, if the user is signed in.
/// If not signed in, or the send fails, the events are put back at the
/// front of the queue for the next flush attempt rather than dropped —
/// bounded by `MAX_QUEUED_EVENTS` above so a long offline stretch still
/// can't grow without limit.
pub async fn flush_events(queue: &AnalyticsQueue) {
    let pending: Vec<AnalyticsEvent> = {
        let mut guard = match queue.0.lock() {
            Ok(g) => g,
            Err(_) => return,
        };
        std::mem::take(&mut *guard)
    };
    if pending.is_empty() {
        return;
    }

    let token = match auth::get_valid_access_token().await {
        Ok(Some(token)) => token,
        Ok(None) => {
            requeue(queue, pending);
            return;
        }
        Err(err) => {
            log::warn!("[ANALYTICS] failed to get access token: {err}");
            requeue(queue, pending);
            return;
        }
    };

    if let Err(err) = AnalyticsClient::new().send_batch(&token, &pending).await {
        log::warn!("[ANALYTICS] flush failed, will retry: {err}");
        requeue(queue, pending);
    }
}

fn requeue(queue: &AnalyticsQueue, mut pending: Vec<AnalyticsEvent>) {
    if let Ok(mut guard) = queue.0.lock() {
        pending.append(&mut guard);
        if pending.len() > MAX_QUEUED_EVENTS {
            let excess = pending.len() - MAX_QUEUED_EVENTS;
            pending.drain(0..excess);
        }
        *guard = pending;
    }
}
