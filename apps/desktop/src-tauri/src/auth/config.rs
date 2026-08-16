/// Supabase project URL, e.g. "https://xxxx.supabase.co". Read from an env
/// var (not hard-coded) so the same build can point at a staging or
/// production Supabase project without a rebuild — mirrors
/// `backend::config::backend_url`'s reasoning.
pub fn supabase_url() -> String {
    std::env::var("SUPABASE_URL").unwrap_or_default()
}

/// Supabase anon/public key. Safe to embed/ship — it identifies the project,
/// not a user; Row Level Security (see supabase/migrations/0001_init.sql) is
/// what actually restricts access, not this key's secrecy. Never the
/// service-role key, which must never reach the desktop app.
pub fn supabase_anon_key() -> String {
    std::env::var("SUPABASE_ANON_KEY").unwrap_or_default()
}

pub fn is_configured() -> bool {
    !supabase_url().is_empty() && !supabase_anon_key().is_empty()
}
