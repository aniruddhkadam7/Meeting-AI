//! On-disk store for Agent records — same load/save/`Mutex<Vec<_>>`/id-scheme
//! pattern as `sales_mode::history` (see that module's doc comment), against
//! its own file (`agents.json`) so agent definitions never collide with any
//! mode's history.

use std::fs;
use std::path::PathBuf;
use std::sync::Mutex;

use tauri::{AppHandle, Manager};

use super::model::Agent;

#[derive(Default)]
pub struct AgentStore(pub Mutex<Vec<Agent>>);

fn store_file_path(app: &AppHandle) -> Result<PathBuf, String> {
    let dir = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("failed to resolve app data directory: {e}"))?;
    fs::create_dir_all(&dir).map_err(|e| format!("failed to create app data directory: {e}"))?;
    Ok(dir.join("agents.json"))
}

pub fn load(app: &AppHandle) -> Vec<Agent> {
    let path = match store_file_path(app) {
        Ok(p) => p,
        Err(err) => {
            log::warn!("agent store: {err}");
            return Vec::new();
        }
    };
    match fs::read_to_string(&path) {
        Ok(contents) => serde_json::from_str(&contents).unwrap_or_default(),
        Err(_) => Vec::new(),
    }
}

fn save(app: &AppHandle, agents: &[Agent]) -> Result<(), String> {
    let path = store_file_path(app)?;
    let json = serde_json::to_string_pretty(agents).map_err(|e| e.to_string())?;
    fs::write(&path, json).map_err(|e| e.to_string())
}

fn now_ms() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

/// Generates a unique agent id. Also used (via `new_id_for_test`, see below)
/// as the id namespace for everything scoped to one agent — its own
/// knowledge base (`agent_id` in the RAG service), its own history file
/// (`agent_history_<id>.json`), so "isolated per agent" falls out of using
/// this one id consistently rather than needing separate id schemes per
/// workspace section.
pub fn new_id() -> String {
    use std::sync::atomic::{AtomicU64, Ordering};
    static COUNTER: AtomicU64 = AtomicU64::new(0);
    let n = COUNTER.fetch_add(1, Ordering::SeqCst);
    format!("agent-{:x}-{:x}", now_ms(), n)
}

fn ensure_loaded(app: &AppHandle, guard: &mut Vec<Agent>) {
    if guard.is_empty() {
        *guard = load(app);
    }
}

#[tauri::command]
pub fn list_agents(app: AppHandle, store: tauri::State<'_, AgentStore>) -> Result<Vec<Agent>, String> {
    let mut guard = store.0.lock().map_err(|e| e.to_string())?;
    ensure_loaded(&app, &mut guard);
    let mut agents = guard.clone();
    agents.sort_by(|a, b| b.updated_at_ms.cmp(&a.updated_at_ms));
    Ok(agents)
}

#[tauri::command]
pub fn get_agent(
    app: AppHandle,
    store: tauri::State<'_, AgentStore>,
    id: String,
) -> Result<Option<Agent>, String> {
    let mut guard = store.0.lock().map_err(|e| e.to_string())?;
    ensure_loaded(&app, &mut guard);
    Ok(guard.iter().find(|a| a.id == id).cloned())
}

#[derive(Debug, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct CreateAgentInput {
    pub name: String,
    #[serde(default)]
    pub base_role: Option<super::model::PredefinedRole>,
    #[serde(default)]
    pub description: Option<String>,
    #[serde(default)]
    pub custom_instructions: Option<String>,
    #[serde(default)]
    pub personalization: Option<super::model::Personalization>,
}

#[tauri::command]
pub fn create_agent(
    app: AppHandle,
    store: tauri::State<'_, AgentStore>,
    input: CreateAgentInput,
) -> Result<Agent, String> {
    let name = input.name.trim();
    if name.is_empty() {
        return Err("agent name cannot be empty".into());
    }
    let now = now_ms();
    let agent = Agent {
        id: new_id(),
        name: name.to_string(),
        base_role: input.base_role,
        description: non_empty(input.description),
        custom_instructions: non_empty(input.custom_instructions),
        personalization: input.personalization.unwrap_or_default(),
        created_at_ms: now,
        updated_at_ms: now,
    };

    let mut guard = store.0.lock().map_err(|e| e.to_string())?;
    ensure_loaded(&app, &mut guard);
    guard.push(agent.clone());
    save(&app, &guard)?;

    crate::analytics::track(
        &app.state::<crate::analytics::AnalyticsQueue>(),
        "agent_created",
        serde_json::json!({
            "has_base_role": agent.base_role.is_some(),
            "base_role": agent.base_role,
        }),
    );

    Ok(agent)
}

#[derive(Debug, serde::Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct UpdateAgentInput {
    pub id: String,
    #[serde(default)]
    pub name: Option<String>,
    #[serde(default)]
    pub base_role: Option<Option<super::model::PredefinedRole>>,
    #[serde(default)]
    pub description: Option<Option<String>>,
    #[serde(default)]
    pub custom_instructions: Option<Option<String>>,
    #[serde(default)]
    pub personalization: Option<super::model::Personalization>,
}

#[tauri::command]
pub fn update_agent(
    app: AppHandle,
    store: tauri::State<'_, AgentStore>,
    input: UpdateAgentInput,
) -> Result<Agent, String> {
    let mut guard = store.0.lock().map_err(|e| e.to_string())?;
    ensure_loaded(&app, &mut guard);

    let agent = guard
        .iter_mut()
        .find(|a| a.id == input.id)
        .ok_or_else(|| format!("no agent with id '{}'", input.id))?;

    if let Some(name) = input.name {
        let trimmed = name.trim();
        if trimmed.is_empty() {
            return Err("agent name cannot be empty".into());
        }
        agent.name = trimmed.to_string();
    }
    if let Some(base_role) = input.base_role {
        agent.base_role = base_role;
    }
    if let Some(description) = input.description {
        agent.description = non_empty(description);
    }
    if let Some(custom_instructions) = input.custom_instructions {
        agent.custom_instructions = non_empty(custom_instructions);
    }
    if let Some(personalization) = input.personalization {
        agent.personalization = personalization;
    }
    agent.updated_at_ms = now_ms();
    let updated = agent.clone();

    save(&app, &guard)?;
    Ok(updated)
}

#[tauri::command]
pub fn delete_agent(app: AppHandle, store: tauri::State<'_, AgentStore>, id: String) -> Result<(), String> {
    let mut guard = store.0.lock().map_err(|e| e.to_string())?;
    ensure_loaded(&app, &mut guard);
    guard.retain(|a| a.id != id);
    save(&app, &guard)?;

    // Best-effort cleanup of this agent's own conversation history file —
    // its knowledge base is cleaned up separately via clear_knowledge_base
    // (RAG service), not from here, since that call is async/network and
    // this command intentionally stays synchronous like sales/consulting's
    // delete commands.
    super::history::delete_history_file(&app, &id);
    Ok(())
}

fn non_empty(value: Option<String>) -> Option<String> {
    value.and_then(|s| {
        let trimmed = s.trim();
        if trimmed.is_empty() {
            None
        } else {
            Some(trimmed.to_string())
        }
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn new_id_is_unique_and_prefixed() {
        let a = new_id();
        let b = new_id();
        assert_ne!(a, b);
        assert!(a.starts_with("agent-"));
        assert!(b.starts_with("agent-"));
    }

    #[test]
    fn non_empty_treats_whitespace_only_as_none() {
        assert_eq!(non_empty(Some("   ".to_string())), None);
        assert_eq!(non_empty(Some("".to_string())), None);
        assert_eq!(non_empty(None), None);
        assert_eq!(non_empty(Some("  hi  ".to_string())), Some("hi".to_string()));
    }
}
