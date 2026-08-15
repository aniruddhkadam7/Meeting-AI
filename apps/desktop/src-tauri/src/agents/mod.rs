//! Custom Agents: predefined-role and fully-custom agent definitions, each
//! with its own isolated Knowledge (packages/rag, scoped by agent_id),
//! Conversations/History (see `history.rs`), Instructions, and
//! Personalization — all driving one shared live overlay via
//! `overlay_window` (already label-parameterized, unchanged by this module)
//! and one generic ask flow (`ask.rs`) instead of a hardcoded mode per role.
//!
//! Interview/Sales/Consulting/Notes Mode are untouched by this module.

pub mod ask;
pub mod history;
pub mod model;
pub mod overlay;
pub mod store;

pub use model::Agent;
