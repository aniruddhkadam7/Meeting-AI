//! Overlay window lifecycle for Custom Agents. One overlay window per agent
//! (label = `agent-overlay-<agent_id>`) so two agents can each have their
//! own overlay open, all built on the existing generic
//! `overlay_window::{show,hide,toggle}_overlay_window` (already
//! label-parameterized for Sales/Consulting Mode) — no changes needed there.

use tauri::AppHandle;

use crate::overlay_window;

fn overlay_label(agent_id: &str) -> String {
    format!("agent-overlay-{agent_id}")
}

async fn run_on_main<T, F>(app: &AppHandle, f: F) -> Result<T, String>
where
    T: Send + 'static,
    F: FnOnce(&AppHandle) -> Result<T, String> + Send + 'static,
{
    let (tx, rx) = std::sync::mpsc::channel();
    let app_for_main = app.clone();
    app.run_on_main_thread(move || {
        let result = f(&app_for_main);
        let _ = tx.send(result);
    })
    .map_err(|e| format!("failed to schedule work on main thread: {e}"))?;

    tauri::async_runtime::spawn_blocking(move || {
        rx.recv()
            .map_err(|e| format!("main-thread task did not respond: {e}"))?
    })
    .await
    .map_err(|e| format!("main-thread task panicked: {e}"))?
}

#[tauri::command]
pub async fn show_agent_overlay(
    app: AppHandle,
    agent_id: String,
    agent_name: String,
) -> Result<overlay_window::OverlayCaptureStatus, String> {
    let label = overlay_label(&agent_id);
    let title = format!("WhitedotAI — {agent_name}");
    run_on_main(&app, move |app| overlay_window::show_overlay_window(app, &label, &title)).await
}

#[tauri::command]
pub async fn hide_agent_overlay(app: AppHandle, agent_id: String) -> Result<(), String> {
    let label = overlay_label(&agent_id);
    run_on_main(&app, move |app| overlay_window::close_overlay_window(app, &label)).await
}

#[tauri::command]
pub async fn toggle_agent_overlay(
    app: AppHandle,
    agent_id: String,
    agent_name: String,
) -> Result<overlay_window::OverlayCaptureStatus, String> {
    let label = overlay_label(&agent_id);
    let title = format!("WhitedotAI — {agent_name}");
    run_on_main(&app, move |app| overlay_window::toggle_overlay_window(app, &label, &title)).await
}

/// Resizes this agent's overlay window in place — backs the Size control in
/// AgentOverlaySettingsPanel.tsx, same fraction-of-monitor scheme Interview
/// Mode's resize_interview_overlay uses.
#[tauri::command]
pub async fn resize_agent_overlay(app: AppHandle, agent_id: String, fraction: f64) -> Result<(), String> {
    let label = overlay_label(&agent_id);
    run_on_main(&app, move |app| overlay_window::resize_overlay(app, &label, fraction)).await
}

#[tauri::command]
pub async fn set_agent_overlay_always_on_top(app: AppHandle, agent_id: String, enabled: bool) -> Result<(), String> {
    let label = overlay_label(&agent_id);
    run_on_main(&app, move |app| overlay_window::set_overlay_always_on_top(app, &label, enabled)).await
}
