// Meeting Mode overlay settings — persisted to localStorage, mirroring
// Interview Mode's overlaySettings.ts so both overlays feel like the same
// product. Only appearance/window fields live here: no role/job
// description/English level/humanization/Auto AI, since those are
// Interview-specific answer-shaping controls with no meeting analogue.
// answerLength/responseStyle (which DO apply to Meeting Mode — see
// PersonalizationPanel.tsx) are shared with Interview Mode via
// overlaySettings.ts rather than duplicated here, so one Personalization
// screen in Settings covers both modes.

export type OverlayDensity = "compact" | "comfortable";
export type OverlaySize = "small" | "medium" | "large";

export interface MeetingOverlaySettings {
  opacity: number; // 0.15 - 1.0 — alpha of the overlay's panel background
  size: OverlaySize;
  fontSize: number; // px, 12 - 20
  density: OverlayDensity;
  dragEnabled: boolean;
}

export const DEFAULT_MEETING_OVERLAY_SETTINGS: MeetingOverlaySettings = {
  opacity: 0.8,
  size: "large",
  fontSize: 14,
  density: "comfortable",
  dragEnabled: true,
};

/// Fraction of the primary monitor's shorter dimension the overlay window
/// occupies for each Small/Medium/Large choice. Must match
/// overlaySettings.ts's SIZE_FRACTIONS — same window-sizing math on the Rust
/// side (`overlay_window::resize_overlay`) is shared by both overlays.
export const SIZE_FRACTIONS: Record<OverlaySize, number> = {
  small: 0.45,
  medium: 0.6,
  large: 0.75,
};

const STORAGE_KEY = "meeting-mode:overlay-settings";
const MIN_USABLE_OPACITY = 0.15;

export function loadMeetingOverlaySettings(): MeetingOverlaySettings {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...DEFAULT_MEETING_OVERLAY_SETTINGS };
    const parsed = JSON.parse(raw);
    const merged: MeetingOverlaySettings = { ...DEFAULT_MEETING_OVERLAY_SETTINGS, ...parsed };
    merged.opacity = Math.min(1, Math.max(MIN_USABLE_OPACITY, merged.opacity));
    return merged;
  } catch {
    return { ...DEFAULT_MEETING_OVERLAY_SETTINGS };
  }
}

export function saveMeetingOverlaySettings(settings: MeetingOverlaySettings): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(settings));
  } catch {
    // localStorage unavailable — settings simply won't persist across restarts.
  }
}
