//! Installs rustls's default crypto provider once per process.
//!
//! `tauri-plugin-updater` (added for Stage 9's automatic-update support)
//! pulls in `reqwest` built against `rustls` rather than the
//! TLS-backend-free `reqwest` build the rest of this crate's HTTP clients
//! use. rustls 0.23+ requires an explicit crypto provider to be installed
//! process-wide before any `rustls::ClientConfig` (and therefore any
//! `reqwest::Client`, including ones with TLS disabled, since the check runs
//! at a lower layer than per-client config) is built — otherwise every
//! `reqwest::Client::builder().build()` in the process panics with "No
//! rustls crypto provider is configured," which surfaced as spurious
//! failures across unrelated `reqwest`-using unit tests (RAG client, backend
//! client) once the updater plugin was added, not just in updater code
//! itself.
//!
//! `install_default()` is itself safe to call from multiple threads/tests —
//! it no-ops (returns `Err`, ignored here) if a provider is already
//! installed, so this is safe to call at the top of both `lib.rs::run()` and
//! any test module that constructs a `reqwest::Client`.
use std::sync::Once;

static INIT: Once = Once::new();

/// Cheap to call from every `reqwest::Client` construction site (production
/// and test) — the actual install only runs once per process via `Once`.
pub fn ensure_installed() {
    INIT.call_once(|| {
        let _ = rustls::crypto::ring::default_provider().install_default();
    });
}
