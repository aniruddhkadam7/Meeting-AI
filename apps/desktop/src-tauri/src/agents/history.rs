//! Per-agent conversation history. Unlike Sales/Consulting Mode (one shared
//! history file for that whole mode), each agent gets its own file
//! (`agent_history_<id>.json`) — this is what makes "isolated Conversations/
//! History per agent" a structural property of the storage rather than a
//! filter applied at read time, matching how RAG's `agent_id` scoping keeps
//! knowledge isolated at the storage layer too.

use std::fs;
use std::path::PathBuf;
use std::sync::Mutex;

use tauri::{AppHandle, Manager};

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct AgentConversationTurn {
    pub question: String,
    pub answer: String,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct AgentConversationEntry {
    pub id: String,
    pub started_at_ms: u64,
    pub ended_at_ms: u64,
    pub turns: Vec<AgentConversationTurn>,
}

/// Keyed by agent id so one Mutex/state value covers every agent's history
/// without needing a dynamically-registered Tauri state per agent.
#[derive(Default)]
pub struct AgentHistoryStore(pub Mutex<std::collections::HashMap<String, Vec<AgentConversationEntry>>>);

fn history_file_path(app: &AppHandle, agent_id: &str) -> Result<PathBuf, String> {
    let dir = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("failed to resolve app data directory: {e}"))?
        .join("agent_history");
    fs::create_dir_all(&dir).map_err(|e| format!("failed to create agent history directory: {e}"))?;
    Ok(dir.join(format!("{agent_id}.json")))
}

fn load(app: &AppHandle, agent_id: &str) -> Vec<AgentConversationEntry> {
    let path = match history_file_path(app, agent_id) {
        Ok(p) => p,
        Err(err) => {
            log::warn!("agent history: {err}");
            return Vec::new();
        }
    };
    match fs::read_to_string(&path) {
        Ok(contents) => serde_json::from_str(&contents).unwrap_or_default(),
        Err(_) => Vec::new(),
    }
}

fn save(app: &AppHandle, agent_id: &str, entries: &[AgentConversationEntry]) -> Result<(), String> {
    let path = history_file_path(app, agent_id)?;
    let json = serde_json::to_string_pretty(entries).map_err(|e| e.to_string())?;
    fs::write(&path, json).map_err(|e| e.to_string())
}

pub fn delete_history_file(app: &AppHandle, agent_id: &str) {
    if let Ok(path) = history_file_path(app, agent_id) {
        let _ = fs::remove_file(path);
    }
}

fn now_ms() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

fn new_id() -> String {
    use std::sync::atomic::{AtomicU64, Ordering};
    static COUNTER: AtomicU64 = AtomicU64::new(0);
    let n = COUNTER.fetch_add(1, Ordering::SeqCst);
    format!("agent-conv-{:x}-{:x}", now_ms(), n)
}

#[tauri::command]
pub fn list_agent_history(
    app: AppHandle,
    store: tauri::State<'_, AgentHistoryStore>,
    agent_id: String,
) -> Result<Vec<AgentConversationEntry>, String> {
    let mut guard = store.0.lock().map_err(|e| e.to_string())?;
    let entries = guard
        .entry(agent_id.clone())
        .or_insert_with(|| load(&app, &agent_id));
    let mut sorted = entries.clone();
    sorted.sort_by(|a, b| b.started_at_ms.cmp(&a.started_at_ms));
    Ok(sorted)
}

#[tauri::command]
pub fn archive_agent_conversation(
    app: AppHandle,
    store: tauri::State<'_, AgentHistoryStore>,
    agent_id: String,
    started_at_ms: u64,
    turns: Vec<AgentConversationTurn>,
) -> Result<Option<AgentConversationEntry>, String> {
    if turns.is_empty() {
        return Ok(None);
    }
    let entry = AgentConversationEntry {
        id: new_id(),
        started_at_ms,
        ended_at_ms: now_ms(),
        turns,
    };

    let mut guard = store.0.lock().map_err(|e| e.to_string())?;
    let entries = guard
        .entry(agent_id.clone())
        .or_insert_with(|| load(&app, &agent_id));
    entries.push(entry.clone());
    save(&app, &agent_id, entries)?;
    Ok(Some(entry))
}

#[tauri::command]
pub fn delete_agent_history_entry(
    app: AppHandle,
    store: tauri::State<'_, AgentHistoryStore>,
    agent_id: String,
    id: String,
) -> Result<(), String> {
    let mut guard = store.0.lock().map_err(|e| e.to_string())?;
    let entries = guard
        .entry(agent_id.clone())
        .or_insert_with(|| load(&app, &agent_id));
    entries.retain(|e| e.id != id);
    save(&app, &agent_id, entries)
}
