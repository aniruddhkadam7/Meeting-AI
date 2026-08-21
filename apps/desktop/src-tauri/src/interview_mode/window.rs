use tauri::{
    window::Color, AppHandle, Emitter, LogicalPosition, LogicalSize, Manager, WebviewUrl, WebviewWindow,
    WebviewWindowBuilder,
};

use crate::windows_capture_protection;

pub const OVERLAY_WINDOW_LABEL: &str = "interview-overlay";
pub const MAIN_WINDOW_LABEL: &str = "main";

// Fallback size used only if the primary monitor can't be queried (see
// `dock_below_main_window` below, which normally computes a square size as a
// fraction of the actual screen instead of a fixed constant).
const OVERLAY_FALLBACK_SIDE: f64 = 560.0;

#[derive(Debug, Clone, Copy, serde::Serialize)]
pub struct OverlayCaptureStatus {
    pub excluded: bool,
}

/// Creates the overlay window if it doesn't already exist, docks it where the
/// main header window currently sits, applies capture exclusion, shows it,
/// then hides the main window — so Interview Mode is the only thing visible,
/// per the requirement that the large Record/Prepare dashboard must never be
/// what's on screen while Interview Mode is active. If the window already
/// exists, just re-docks (the header may have moved/resized since last time)
/// and shows/focuses it.
///
/// The main window is hidden LAST, only once the overlay has actually been
/// docked/shown — not first. Hiding it first left a visible gap between the
/// main window vanishing and the overlay actually appearing (webview
/// creation + the capture-exclusion IOCTL call both take real time on a
/// window being created for the first time), which read as the whole app
/// having closed/crashed rather than a fast transition to Interview Mode.
/// This also means the dock position is computed from the main window while
/// it's still visible/on-screen, before it's hidden.
pub fn show_overlay_window(app: &AppHandle) -> Result<OverlayCaptureStatus, String> {
    let excluded = if let Some(existing) = app.get_webview_window(OVERLAY_WINDOW_LABEL) {
        log::info!("Interview Mode: reusing existing overlay window");
        dock_below_main_window(app, &existing, false);
        existing.show().map_err(|e| e.to_string())?;
        existing.set_focus().map_err(|e| e.to_string())?;
        let excluded = windows_capture_protection::enable_capture_exclusion(&existing).is_ok();
        log::info!("Interview Mode: capture exclusion re-applied, excluded={excluded}");
        excluded
    } else {
        log::info!("Interview Mode: creating new overlay window");
        let window = build_overlay_window(app)?;
        dock_below_main_window(app, &window, true);

        let excluded = windows_capture_protection::enable_capture_exclusion(&window).is_ok();
        if excluded {
            log::info!("Interview Mode: screen-capture exclusion ENABLED for overlay HWND");
        } else {
            log::warn!("Interview Mode: screen-capture exclusion FAILED/UNAVAILABLE for overlay HWND");
        }

        window.show().map_err(|e| e.to_string())?;
        window.set_focus().map_err(|e| e.to_string())?;
        log::info!("Interview Mode: overlay window shown and focused");
        excluded
    };

    if let Some(main) = app.get_webview_window(MAIN_WINDOW_LABEL) {
        if let Err(e) = main.hide() {
            log::warn!("failed to hide main window when entering Interview Mode: {e}");
        }
    } else {
        log::warn!("main window not found by label '{MAIN_WINDOW_LABEL}' when entering Interview Mode");
    }

    Ok(OverlayCaptureStatus { excluded })
}

/// Hides the overlay and brings the main window back, since Interview Mode
/// hides it on entry (see `show_overlay_window`).
///
/// Also emits `interview-mode:overlay-closed` to every window. The overlay
/// and main window are separate webviews with entirely separate React
/// trees — there is no shared state between them — so the main window's own
/// "Start"/"Stop" session status has no way to learn the session ended
/// unless it was the one that called this in the first place (e.g. the user
/// clicked the overlay's own ✕/"Yes, end interview" instead of the main
/// window's Stop button). Without this event, the main window keeps
/// showing "Stop" after the overlay is already gone, requiring a redundant
/// click to catch up.
pub fn close_overlay_window(app: &AppHandle) -> Result<(), String> {
    if let Some(window) = app.get_webview_window(OVERLAY_WINDOW_LABEL) {
        window.hide().map_err(|e| e.to_string())?;
    }
    if let Some(main) = app.get_webview_window(MAIN_WINDOW_LABEL) {
        main.show().map_err(|e| e.to_string())?;
        main.set_focus().map_err(|e| e.to_string())?;
    }
    let _ = app.emit("interview-mode:overlay-closed", ());
    Ok(())
}

/// Applied from the overlay's Settings panel (Always-on-top toggle). Errors
/// are logged rather than propagated to keep this best-effort — the overlay
/// remaining on top by default is more important than a failed toggle
/// blocking the rest of the settings panel from working.
pub fn set_overlay_always_on_top(app: &AppHandle, enabled: bool) -> Result<(), String> {
    if let Some(window) = app.get_webview_window(OVERLAY_WINDOW_LABEL) {
        window.set_always_on_top(enabled).map_err(|e| e.to_string())?;
    }
    Ok(())
}

/// Resizes the overlay to a square fraction of the primary monitor's shorter
/// dimension, then re-docks it below the main window — same math as
/// `dock_below_main_window`'s default (`DEFAULT_SIZE_FRACTION`), just
/// parameterized by the Settings panel's Small/Medium/Large choice so the
/// window itself changes, not only its CSS padding.
pub fn resize_overlay(app: &AppHandle, fraction: f64) -> Result<(), String> {
    let Some(window) = app.get_webview_window(OVERLAY_WINDOW_LABEL) else {
        return Ok(());
    };
    let Ok(Some(monitor)) = window.primary_monitor() else {
        return Ok(());
    };
    let scale = monitor.scale_factor();
    let monitor_size = monitor.size().to_logical::<f64>(scale);
    let side = (monitor_size.width.min(monitor_size.height) * fraction).max(320.0);

    window
        .set_size(LogicalSize::new(side, side))
        .map_err(|e| e.to_string())?;
    dock_below_main_window(app, &window, false);
    Ok(())
}

pub fn toggle_overlay_window(app: &AppHandle) -> Result<OverlayCaptureStatus, String> {
    if let Some(window) = app.get_webview_window(OVERLAY_WINDOW_LABEL) {
        let visible = window.is_visible().unwrap_or(false);
        if visible {
            close_overlay_window(app)?;
            return Ok(OverlayCaptureStatus { excluded: is_capture_excluded(app) });
        }
    }
    show_overlay_window(app)
}

pub fn is_capture_excluded(app: &AppHandle) -> bool {
    // There is no Win32 "get" counterpart exposed by the `windows` crate
    // binding used here for display affinity, so this tracks the last known
    // result from `show_overlay_window`'s own enable call rather than
    // re-querying the OS. Re-applying on every show call (see
    // `show_overlay_window` above) keeps this accurate in practice.
    app.get_webview_window(OVERLAY_WINDOW_LABEL).is_some()
}

fn build_overlay_window(app: &AppHandle) -> Result<WebviewWindow, String> {
    WebviewWindowBuilder::new(app, OVERLAY_WINDOW_LABEL, WebviewUrl::App("index.html".into()))
        .title("Smallbird Interview — Overlay")
        .inner_size(OVERLAY_FALLBACK_SIDE, OVERLAY_FALLBACK_SIDE)
        .min_inner_size(320.0, 320.0)
        .resizable(true)
        .decorations(false)
        .transparent(true)
        // On Windows, WebView2's own background still paints opaque unless a
        // fully-transparent background color is set explicitly in addition to
        // `.transparent(true)` (which only makes the window able to host
        // transparency, not each pixel actually transparent by default) —
        // without this the overlay renders as an opaque dark rectangle
        // instead of a translucent floating card.
        .background_color(Color(0, 0, 0, 0))
        .always_on_top(true)
        .skip_taskbar(true)
        .shadow(false)
        .visible(false)
        .focused(false)
        .build()
        .map_err(|e| format!("failed to create overlay window: {e}"))
}

/// Default fraction of the primary monitor's shorter dimension the overlay
/// occupies on first creation, before any explicit resize. Matches "large" in
/// the settings panel's Small/Medium/Large choice (`SIZE_FRACTIONS` in
/// OverlaySettingsPanel.tsx) — kept as one named constant here rather than a
/// bare `0.75` so the two don't silently drift apart.
const DEFAULT_SIZE_FRACTION: f64 = 0.75;

/// Gap between the main window's bottom edge and the overlay's top edge, so
/// the overlay reads as its own attached panel rather than touching the
/// header edge-to-edge — same idea as `HeaderDropdown.tsx`'s `GAP_ABOVE` for
/// the header's own in-window popovers.
const DOCK_GAP: f64 = 8.0;

/// Docks the overlay directly beneath the main header window, aligned to the
/// header's left edge. If `apply_default_size` is set (only true right after
/// `build_overlay_window` creates a brand-new window), also sizes it to a
/// square roughly three-quarters of the primary monitor's shorter dimension
/// first — square rather than a wide/short rectangle, per explicit feedback
/// that the wide aspect ratio looked wrong. `resize_overlay` sets its own
/// explicit size before calling this purely for repositioning, so it always
/// passes `false` to avoid overwriting that.
///
/// Falls back to centering on the primary monitor if the main window can't be
/// found/queried (should not happen in practice — the main window always
/// exists — but keeps this from panicking if it somehow doesn't).
fn dock_below_main_window(app: &AppHandle, window: &WebviewWindow, apply_default_size: bool) {
    if apply_default_size {
        if let Ok(Some(monitor)) = window.primary_monitor() {
            let monitor_scale = monitor.scale_factor();
            let monitor_size = monitor.size().to_logical::<f64>(monitor_scale);
            let side = (monitor_size.width.min(monitor_size.height) * DEFAULT_SIZE_FRACTION).max(360.0);
            let _ = window.set_size(LogicalSize::new(side, side));
        }
    }

    let Some(main) = app.get_webview_window(MAIN_WINDOW_LABEL) else {
        center_on_primary_monitor(window);
        return;
    };
    let Ok(main_pos) = main.outer_position() else {
        center_on_primary_monitor(window);
        return;
    };
    let Ok(main_size) = main.outer_size() else {
        center_on_primary_monitor(window);
        return;
    };
    let scale = main.scale_factor().unwrap_or(1.0);
    let main_pos = main_pos.to_logical::<f64>(scale);
    let main_size = main_size.to_logical::<f64>(scale);

    let x = main_pos.x;
    let y = main_pos.y + main_size.height + DOCK_GAP;
    let _ = window.set_position(LogicalPosition::new(x, y));
}

fn center_on_primary_monitor(window: &WebviewWindow) {
    let Ok(Some(monitor)) = window.primary_monitor() else {
        return;
    };
    let scale = monitor.scale_factor();
    let monitor_size = monitor.size().to_logical::<f64>(scale);
    let monitor_pos = monitor.position().to_logical::<f64>(scale);
    let Ok(size) = window.inner_size() else {
        return;
    };
    let size = size.to_logical::<f64>(scale);

    let x = monitor_pos.x + (monitor_size.width - size.width) / 2.0;
    let y = monitor_pos.y + (monitor_size.height - size.height) / 2.0;
    let _ = window.set_position(LogicalPosition::new(x, y));
}
