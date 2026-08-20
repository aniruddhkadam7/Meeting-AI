//! Shared frameless/always-on-top overlay window mechanics for Sales Mode and
//! Consulting Mode, parameterized by window label instead of the
//! Interview-Mode-specific constants baked into `interview_mode::window`.
//!
//! This is a deliberate near-duplicate of `interview_mode/window.rs` rather
//! than a refactor of it — Interview Mode must stay unchanged, so its module
//! is left untouched and this sibling module carries the same logic
//! parameterized by label for the two new live-call modes.

use tauri::{
    window::Color, AppHandle, Emitter, LogicalPosition, LogicalSize, Manager, WebviewUrl, WebviewWindow,
    WebviewWindowBuilder,
};

use crate::windows_capture_protection;

pub const MAIN_WINDOW_LABEL: &str = "main";

const OVERLAY_FALLBACK_SIDE: f64 = 560.0;
const DEFAULT_SIZE_FRACTION: f64 = 0.75;

#[derive(Debug, Clone, Copy, serde::Serialize)]
pub struct OverlayCaptureStatus {
    pub excluded: bool,
}

/// Creates the overlay window (if it doesn't exist), positions it centered on
/// the primary monitor, applies capture exclusion, hides the main window, and
/// shows it. `title` is the OS window title; `label` distinguishes this
/// overlay from Interview Mode's and from the other live-call mode's overlay.
pub fn show_overlay_window(app: &AppHandle, label: &str, title: &str) -> Result<OverlayCaptureStatus, String> {
    if let Some(main) = app.get_webview_window(MAIN_WINDOW_LABEL) {
        if let Err(e) = main.hide() {
            log::warn!("failed to hide main window when entering overlay '{label}': {e}");
        }
    }

    if let Some(existing) = app.get_webview_window(label) {
        existing.show().map_err(|e| e.to_string())?;
        existing.set_focus().map_err(|e| e.to_string())?;
        let excluded = windows_capture_protection::enable_capture_exclusion(&existing).is_ok();
        return Ok(OverlayCaptureStatus { excluded });
    }

    let window = build_overlay_window(app, label, title)?;
    size_and_center(&window, DEFAULT_SIZE_FRACTION);

    let excluded = windows_capture_protection::enable_capture_exclusion(&window).is_ok();
    if excluded {
        log::info!("overlay '{label}': screen-capture exclusion ENABLED");
    } else {
        log::warn!("overlay '{label}': screen-capture exclusion FAILED/UNAVAILABLE");
    }

    window.show().map_err(|e| e.to_string())?;
    window.set_focus().map_err(|e| e.to_string())?;

    Ok(OverlayCaptureStatus { excluded })
}

/// Also emits `interview-mode:overlay-closed` to every window — see the doc
/// comment on `interview_mode::window::close_overlay_window` for why: the
/// overlay and main window are separate webviews with no shared React
/// state, so the main window's own session status has no other way to learn
/// the overlay closed unless it was the one that called this. Reusing the
/// same event name (rather than a Sales/Consulting/Meeting-specific one)
/// keeps the main window's listener a single one covering every mode, since
/// it only ever has one active overlay/session at a time regardless of mode.
pub fn close_overlay_window(app: &AppHandle, label: &str) -> Result<(), String> {
    if let Some(window) = app.get_webview_window(label) {
        window.hide().map_err(|e| e.to_string())?;
    }
    if let Some(main) = app.get_webview_window(MAIN_WINDOW_LABEL) {
        main.show().map_err(|e| e.to_string())?;
        main.set_focus().map_err(|e| e.to_string())?;
    }
    let _ = app.emit("interview-mode:overlay-closed", ());
    Ok(())
}

pub fn toggle_overlay_window(app: &AppHandle, label: &str, title: &str) -> Result<OverlayCaptureStatus, String> {
    if let Some(window) = app.get_webview_window(label) {
        let visible = window.is_visible().unwrap_or(false);
        if visible {
            close_overlay_window(app, label)?;
            return Ok(OverlayCaptureStatus { excluded: is_capture_excluded(app, label) });
        }
    }
    show_overlay_window(app, label, title)
}

pub fn is_capture_excluded(app: &AppHandle, label: &str) -> bool {
    app.get_webview_window(label).is_some()
}

pub fn set_overlay_always_on_top(app: &AppHandle, label: &str, enabled: bool) -> Result<(), String> {
    if let Some(window) = app.get_webview_window(label) {
        window.set_always_on_top(enabled).map_err(|e| e.to_string())?;
    }
    Ok(())
}

pub fn resize_overlay(app: &AppHandle, label: &str, fraction: f64) -> Result<(), String> {
    let Some(window) = app.get_webview_window(label) else {
        return Ok(());
    };
    size_and_center(&window, fraction);
    Ok(())
}

fn build_overlay_window(app: &AppHandle, label: &str, title: &str) -> Result<WebviewWindow, String> {
    WebviewWindowBuilder::new(app, label, WebviewUrl::App("index.html".into()))
        .title(title)
        .inner_size(OVERLAY_FALLBACK_SIDE, OVERLAY_FALLBACK_SIDE)
        .min_inner_size(320.0, 320.0)
        .resizable(true)
        .decorations(false)
        .transparent(true)
        .background_color(Color(0, 0, 0, 0))
        .always_on_top(true)
        .skip_taskbar(true)
        .shadow(false)
        .visible(false)
        .focused(false)
        .build()
        .map_err(|e| format!("failed to create overlay window '{label}': {e}"))
}

fn size_and_center(window: &WebviewWindow, fraction: f64) {
    let Ok(Some(monitor)) = window.primary_monitor() else {
        return;
    };
    let scale = monitor.scale_factor();
    let monitor_size = monitor.size().to_logical::<f64>(scale);
    let monitor_pos = monitor.position().to_logical::<f64>(scale);

    let side = (monitor_size.width.min(monitor_size.height) * fraction).max(320.0);
    let x = monitor_pos.x + (monitor_size.width - side) / 2.0;
    let y = monitor_pos.y + (monitor_size.height - side) / 2.0;

    let _ = window.set_size(LogicalSize::new(side, side));
    let _ = window.set_position(LogicalPosition::new(x, y));
}
