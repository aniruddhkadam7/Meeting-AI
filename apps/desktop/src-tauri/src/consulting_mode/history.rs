//! On-disk archive for Consulting Mode, grouped by client engagement (unlike
//! Sales' one-off calls, a consulting engagement spans many sessions with the
//! same client and needs its own persisted context — see `EngagementContext`
//! below, which is what gives the live ask flow cross-session memory).

use std::fs;
use std::path::PathBuf;
use std::sync::Mutex;

use tauri::{AppHandle, Manager};

use crate::backend::ConsultingNote;

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct ConsultingHistoryTurn {
    pub speaker: String,
    pub text: String,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct ConsultingSessionEntry {
    pub id: String,
    pub started_at_ms: u64,
    pub ended_at_ms: u64,
    pub turns: Vec<ConsultingHistoryTurn>,
    pub notes: ConsultingNote,
}

#[derive(Debug, Clone, serde::Serialize, serde::Deserialize)]
pub struct Engagement {
    pub id: String,
    pub client_name: String,
    #[serde(default)]
    pub project_name: Option<String>,
    pub created_at_ms: u64,
    #[serde(default)]
    pub sessions: Vec<ConsultingSessionEntry>,
}

impl Engagement {
    /// Rolling digest of prior sessions sent as `engagement_context` in the
    /// live ask flow — the last few sessions' summaries, not the full
    /// transcript history, to keep the prompt bounded. See
    /// `ask_consulting_question` / `ConsultingAskOptions::engagement_context`.
    pub fn context_digest(&self) -> Option<String> {
        if self.sessions.is_empty() {
            return None;
        }
        let recent: Vec<&ConsultingSessionEntry> = self.sessions.iter().rev().take(5).collect();
        let mut parts = Vec::new();
        for session in recent.iter().rev() {
            if !session.notes.summary.is_empty() {
                parts.push(session.notes.summary.clone());
            }
        }
        if parts.is_empty() {
            None
        } else {
            Some(parts.join("\n\n"))
        }
    }
}

#[derive(Default)]
pub struct ConsultingHistoryStore(pub Mutex<Vec<Engagement>>);

fn history_file_path(app: &AppHandle) -> Result<PathBuf, String> {
    let dir = app
        .path()
        .app_data_dir()
        .map_err(|e| format!("failed to resolve app data directory: {e}"))?;
    fs::create_dir_all(&dir).map_err(|e| format!("failed to create app data directory: {e}"))?;
    Ok(dir.join("consulting_history.json"))
}

pub fn load(app: &AppHandle) -> Vec<Engagement> {
    let path = match history_file_path(app) {
        Ok(p) => p,
        Err(err) => {
            log::warn!("consulting history: {err}");
            return Vec::new();
        }
    };
    match fs::read_to_string(&path) {
        Ok(contents) => serde_json::from_str(&contents).unwrap_or_default(),
        Err(_) => Vec::new(),
    }
}

fn save(app: &AppHandle, engagements: &[Engagement]) -> Result<(), String> {
    let path = history_file_path(app)?;
    let json = serde_json::to_string_pretty(engagements).map_err(|e| e.to_string())?;
    fs::write(&path, json).map_err(|e| e.to_string())
}

fn now_ms() -> u64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .map(|d| d.as_millis() as u64)
        .unwrap_or(0)
}

fn new_id(prefix: &str) -> String {
    use std::sync::atomic::{AtomicU64, Ordering};
    static COUNTER: AtomicU64 = AtomicU64::new(0);
    let n = COUNTER.fetch_add(1, Ordering::SeqCst);
    format!("{prefix}-{:x}-{:x}", now_ms(), n)
}

fn ensure_loaded(app: &AppHandle, guard: &mut Vec<Engagement>) {
    if guard.is_empty() {
        *guard = load(app);
    }
}

#[tauri::command]
pub fn list_engagements(app: AppHandle, store: tauri::State<'_, ConsultingHistoryStore>) -> Vec<Engagement> {
    let mut guard = store.0.lock().unwrap();
    ensure_loaded(&app, &mut guard);
    let mut engagements = guard.clone();
    engagements.sort_by(|a, b| b.created_at_ms.cmp(&a.created_at_ms));
    engagements
}

#[tauri::command]
pub fn create_engagement(
    app: AppHandle,
    store: tauri::State<'_, ConsultingHistoryStore>,
    client_name: String,
    project_name: Option<String>,
) -> Result<Engagement, String> {
    let mut guard = store.0.lock().map_err(|e| e.to_string())?;
    ensure_loaded(&app, &mut guard);

    let engagement = Engagement {
        id: new_id("eng"),
        client_name,
        project_name: project_name.filter(|s| !s.trim().is_empty()),
        created_at_ms: now_ms(),
        sessions: Vec::new(),
    };
    guard.push(engagement.clone());
    save(&app, &guard)?;
    Ok(engagement)
}

#[tauri::command]
pub fn get_engagement_context(
    app: AppHandle,
    store: tauri::State<'_, ConsultingHistoryStore>,
    engagement_id: String,
) -> Option<String> {
    let mut guard = store.0.lock().unwrap();
    ensure_loaded(&app, &mut guard);
    guard.iter().find(|e| e.id == engagement_id).and_then(|e| e.context_digest())
}

/// Archives one finished session under an existing engagement. Skipped (like
/// Interview Mode's `archive_interview_session`) when there's no transcript,
/// so an idle open doesn't clutter the engagement's history.
#[tauri::command]
pub fn archive_consulting_session(
    app: AppHandle,
    store: tauri::State<'_, ConsultingHistoryStore>,
    engagement_id: String,
    started_at_ms: u64,
    turns: Vec<ConsultingHistoryTurn>,
    notes: ConsultingNote,
) -> Result<Option<ConsultingSessionEntry>, String> {
    if turns.is_empty() {
        return Ok(None);
    }
    let entry = ConsultingSessionEntry {
        id: new_id("sess"),
        started_at_ms,
        ended_at_ms: now_ms(),
        turns,
        notes,
    };

    let mut guard = store.0.lock().map_err(|e| e.to_string())?;
    ensure_loaded(&app, &mut guard);
    let engagement = guard
        .iter_mut()
        .find(|e| e.id == engagement_id)
        .ok_or_else(|| "engagement not found".to_string())?;
    engagement.sessions.push(entry.clone());
    save(&app, &guard)?;
    Ok(Some(entry))
}

#[tauri::command]
pub fn delete_engagement(
    app: AppHandle,
    store: tauri::State<'_, ConsultingHistoryStore>,
    id: String,
) -> Result<(), String> {
    let mut guard = store.0.lock().map_err(|e| e.to_string())?;
    ensure_loaded(&app, &mut guard);
    guard.retain(|e| e.id != id);
    save(&app, &guard)
}
