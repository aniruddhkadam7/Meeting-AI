//! Main window titlebar cosmetics, plus the compact header's anchored
//! dropdown/popover mechanics. Native Maximize/Restore (via the OS titlebar
//! controls, since `decorations` is left at its default `true`) is the only
//! way the user directly resizes the window — there is no in-app expand
//! button. But a Tauri webview can only ever paint inside its own real OS
//! window bounds, and the compact window is a fixed 760x56 toolbar with no
//! slack below the header, so an in-window dropdown/popover (Mode, Context,
//! Settings, Account) needs actual client-area room to render into. This
//! module grows the window's real height just enough to fit whichever
//! popover is open — invisibly, since the popover's own content fills that
//! extra space the instant it appears, reading as "a dropdown opened" rather
//! than "the window resized" — and snaps back to the 56px toolbar height the
//! moment the popover closes. Width and the window's top-left position never
//! change; only height moves, and only while not natively maximized.

use tauri::{AppHandle, LogicalPosition, LogicalSize, Manager};
use windows::Win32::Foundation::COLORREF;
use windows::Win32::Graphics::Dwm::{DwmSetWindowAttribute, DWMWA_CAPTION_COLOR, DWMWA_TEXT_COLOR};

const MAIN_WINDOW_LABEL: &str = "main";

const COMPACT_WIDTH: f64 = 760.0;
const COMPACT_HEIGHT: f64 = 56.0;

// Small gap from the very top of the screen so the window doesn't sit flush
// against the physical screen edge — reads as "top of the screen" without
// touching it.
const TOP_MARGIN: f64 = 24.0;

/// Positions the main window horizontally centered and near the top of the
/// primary monitor, then shows it. Called once at launch (see `lib.rs`'s
/// setup hook) so the compact toolbar always opens in the same predictable
/// spot rather than wherever the OS last placed it or however it cascades
/// new windows. The window starts `"visible": false` in tauri.conf.json
/// specifically so this can position it first — showing it already visible
/// at its eventual default OS placement and then immediately moving it
/// would be a visible jump/flash on every launch.
pub fn position_top_center(app: &AppHandle) {
    let Some(window) = app.get_webview_window(MAIN_WINDOW_LABEL) else {
        return;
    };
    if let Ok(Some(monitor)) = window.primary_monitor() {
        let scale = monitor.scale_factor();
        let monitor_size = monitor.size().to_logical::<f64>(scale);
        let monitor_pos = monitor.position().to_logical::<f64>(scale);

        let x = monitor_pos.x + (monitor_size.width - COMPACT_WIDTH) / 2.0;
        let y = monitor_pos.y + TOP_MARGIN;

        let _ = window.set_position(LogicalPosition::new(x, y));
    }
    let _ = window.show();
}

/// Grows the main window's height to fit an open popover of `content_height`
/// logical pixels below the 56px header, or shrinks it back to the bare
/// 56px toolbar when `content_height` is 0 (popover closed). No-ops while
/// the window is natively maximized — the user's own Maximize/Restore is
/// left alone rather than fought over.
#[tauri::command]
pub fn set_popover_content_height(app: AppHandle, content_height: f64) -> Result<(), String> {
    let Some(window) = app.get_webview_window(MAIN_WINDOW_LABEL) else {
        return Ok(());
    };
    if window.is_maximized().unwrap_or(false) {
        return Ok(());
    }

    let target_height = COMPACT_HEIGHT + content_height.max(0.0);

    // The OS clamps set_size to whatever min size is currently in effect,
    // so the floor has to drop to the bare toolbar height before shrinking
    // back down to it — otherwise a shrink from an open popover back to
    // 56px would silently no-op against its own taller min size.
    window
        .set_min_size(Some(LogicalSize::new(COMPACT_WIDTH, COMPACT_HEIGHT)))
        .map_err(|e| e.to_string())?;
    window
        .set_size(LogicalSize::new(COMPACT_WIDTH, target_height))
        .map_err(|e| e.to_string())?;
    Ok(())
}

/// Matches the native Windows title bar's caption/text color to the app
/// header's own background (`--surface: #ffffff` / `--text: #17181c` in
/// App.css) so the OS title bar and the in-app header read as one seamless
/// surface, with only the header's own subtle border as a divider between
/// them. Windows 11 only (`DWMWA_CAPTION_COLOR` is a no-op — not an error —
/// on Windows 10, which has no per-window caption color API); failures are
/// logged, never fatal, since this is a cosmetic touch, not functional.
pub fn apply_light_titlebar(app: &AppHandle) {
    let Some(window) = app.get_webview_window(MAIN_WINDOW_LABEL) else {
        return;
    };
    let Ok(hwnd) = window.hwnd() else {
        return;
    };

    // COLORREF is 0x00BBGGRR, not 0x00RRGGBB.
    const CAPTION_COLOR: u32 = 0x00FFFFFF; // #ffffff, R=G=B=0xff so byte order doesn't matter here
    const TEXT_COLOR: u32 = 0x001C1817; // #17181c

    unsafe {
        let caption = COLORREF(CAPTION_COLOR);
        if let Err(e) = DwmSetWindowAttribute(
            hwnd,
            DWMWA_CAPTION_COLOR,
            &caption as *const _ as *const std::ffi::c_void,
            std::mem::size_of::<COLORREF>() as u32,
        ) {
            log::warn!("failed to set title bar caption color (expected on Windows 10): {e}");
        }
        let text = COLORREF(TEXT_COLOR);
        if let Err(e) = DwmSetWindowAttribute(
            hwnd,
            DWMWA_TEXT_COLOR,
            &text as *const _ as *const std::ffi::c_void,
            std::mem::size_of::<COLORREF>() as u32,
        ) {
            log::warn!("failed to set title bar text color (expected on Windows 10): {e}");
        }
    }
}
