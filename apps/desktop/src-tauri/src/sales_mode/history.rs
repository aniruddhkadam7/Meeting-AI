//! On-disk archive of past Sales Mode calls — same load/save/Mutex<Vec<_>>
//! pattern as `crate::history` (Interview Mode's), against its own file so
//! the two data shapes never collide.

use std::fs;
use std::path::PathBuf;
use std::sync::Mutex;

use tauri::{AppHandle, Manager};

use crate::backend::SalesCallSummary;

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct SalesHistoryTurn {
    pub speaker: String,
    pub text: String,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct SalesHistoryEntry {
    pub id: String,
    pub started_at_ms: u64,
    pub ended_at_ms: u64,
    #[serde(default)]
    pub customer_name: Option<String>,
    #[serde(default)]
    pub company_name: Option<String>,
    pub turns: Vec<SalesHistoryTurn>,
    pub summary: SalesCallSummary,
}

#[derive(Default)]
pub struct SalesHistoryStore(pub Mutex<Vec<SalesHistoryEntry>>);

fn history_file_path(app: &AppHandle) -> Result<PathBuf, String> {
    let dir = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("failed to resolve app data directory: {e}"))?;
    fs::create_dir_all(&dir).map_err(|e| format!("failed to create app data directory: {e}"))?;
    Ok(dir.join("sales_history.json"))
}

pub fn load(app: &AppHandle) -> Vec<SalesHistoryEntry> {
    let path = match history_file_path(app) {
        Ok(p) => p,
        Err(err) => {
            log::warn!("sales history: {err}");
            return Vec::new();
        }
    };
    match fs::read_to_string(&path) {
        Ok(contents) => serde_json::from_str(&contents).unwrap_or_default(),
        Err(_) => Vec::new(),
    }
}

fn save(app: &AppHandle, entries: &[SalesHistoryEntry]) -> Result<(), String> {
    let path = history_file_path(app)?;
    let json = serde_json::to_string_pretty(entries).map_err(|e| e.to_string())?;
    fs::write(&path, json).map_err(|e| e.to_string())
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
    format!("sales-{:x}-{:x}", now_ms(), n)
}

#[tauri::command]
pub fn list_sales_history(app: AppHandle, store: tauri::State<'_, SalesHistoryStore>) -> Vec<SalesHistoryEntry> {
    let mut guard = store.0.lock().unwrap();
    if guard.is_empty() {
        *guard = load(&app);
    }
    let mut entries = guard.clone();
    entries.sort_by(|a, b| b.started_at_ms.cmp(&a.started_at_ms));
    entries
}

#[tauri::command]
pub fn archive_sales_call(
    app: AppHandle,
    store: tauri::State<'_, SalesHistoryStore>,
    started_at_ms: u64,
    customer_name: Option<String>,
    company_name: Option<String>,
    turns: Vec<SalesHistoryTurn>,
    summary: SalesCallSummary,
) -> Result<Option<SalesHistoryEntry>, String> {
    if turns.is_empty() {
        return Ok(None);
    }
    let entry = SalesHistoryEntry {
        id: new_id(),
        started_at_ms,
        ended_at_ms: now_ms(),
        customer_name: customer_name.filter(|s| !s.trim().is_empty()),
        company_name: company_name.filter(|s| !s.trim().is_empty()),
        turns,
        summary,
    };

    let mut guard = store.0.lock().map_err(|e| e.to_string())?;
    if guard.is_empty() {
        *guard = load(&app);
    }
    guard.push(entry.clone());
    save(&app, &guard)?;
    Ok(Some(entry))
}

#[tauri::command]
pub fn delete_sales_history_entry(
    app: AppHandle,
    store: tauri::State<'_, SalesHistoryStore>,
    id: String,
) -> Result<(), String> {
    let mut guard = store.0.lock().map_err(|e| e.to_string())?;
    if guard.is_empty() {
        *guard = load(&app);
    }
    guard.retain(|e| e.id != id);
    save(&app, &guard)
}
