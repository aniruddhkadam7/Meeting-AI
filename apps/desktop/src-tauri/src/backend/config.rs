/// Reads the backend base URL from the `BACKEND_URL` environment variable,
/// defaulting to the local dev server. The desktop app must never hard-code a
/// production URL — this is the single source of truth for where "the backend"
/// is, and it is intentionally simple (env var, not a settings file) for Phase 1.
pub fn backend_url() -> String {
    std::env::var("BACKEND_URL").unwrap_or_else(|_| "http://127.0.0.1:8000".to_string())
}
