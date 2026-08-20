//! Smallbird Cloud sync: local-first mirroring of the desktop's on-disk Agent
//! store (`agents::store::AgentStore`, `agents.json`) to Smallbird Cloud, so a
//! signed-in user's agents survive a reinstall or (later) show up on a
//! second machine.
//!
//! Local storage remains the source of truth for offline use — every agent
//! CRUD command still writes to disk first and works with no network at
//! all. Sync is additive: `sync_agents_now` pushes local changes then pulls
//! whatever the cloud has that's newer, called after sign-in and after any
//! local agent mutation (best-effort, failures are logged not surfaced as
//! command errors, since a sync hiccup must never block editing an agent).

mod client;
pub mod commands;
