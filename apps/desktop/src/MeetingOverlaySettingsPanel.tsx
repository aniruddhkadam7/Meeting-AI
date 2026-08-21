import { invoke } from "@tauri-apps/api/core";
import { useState } from "react";
import {
  DEFAULT_MEETING_OVERLAY_SETTINGS,
  SIZE_FRACTIONS,
  type MeetingOverlaySettings,
  type OverlayDensity,
  type OverlaySize,
} from "./meetingOverlaySettings";
import { Select } from "./ui";

interface Props {
  settings: MeetingOverlaySettings;
  onChange: (settings: MeetingOverlaySettings) => void;
  onClose: () => void;
  captureExcluded: boolean | null;
}

/// Meeting Mode's Settings panel — the Appearance-only subset of Interview
/// Mode's OverlaySettingsPanel (see that file), since Meeting Mode has no
/// answer-shaping controls (role, job description, Auto AI, etc.) to show.
export function MeetingOverlaySettingsPanel({ settings, onChange, onClose, captureExcluded }: Props) {
  const [alwaysOnTop, setAlwaysOnTop] = useState(true);

  const set = <K extends keyof MeetingOverlaySettings>(key: K, value: MeetingOverlaySettings[K]) => {
    onChange({ ...settings, [key]: value });
  };

  const changeSize = (size: OverlaySize) => {
    set("size", size);
    invoke("resize_meeting_overlay", { fraction: SIZE_FRACTIONS[size] }).catch(() => {
      // Best-effort — the CSS size-* class still applies even if the actual
      // OS window resize fails, so the panel remains usable either way.
    });
  };

  const toggleAlwaysOnTop = () => {
    const next = !alwaysOnTop;
    setAlwaysOnTop(next);
    invoke("set_meeting_overlay_always_on_top", { enabled: next }).catch(() => {
      // Best-effort — the window remains on top by default even if this call
      // fails, so there is nothing actionable to show the user here.
    });
  };

  const resetDefaults = () => onChange({ ...DEFAULT_MEETING_OVERLAY_SETTINGS });

  return (
    <div className="overlay-body overlay-settings">
      <div className="overlay-settings-section">
        <span className="overlay-settings-label">Appearance</span>

        <label className="overlay-settings-row">
          <span>Opacity</span>
          <input
            type="range"
            min={0.15}
            max={1}
            step={0.02}
            value={settings.opacity}
            onChange={(e) => set("opacity", Number(e.target.value))}
          />
        </label>

        <div className="overlay-settings-row">
          <span>Overlay size</span>
          <Select
            className="select-overlay"
            value={settings.size}
            onChange={changeSize}
            aria-label="Overlay size"
            options={[
              { value: "small", label: "Small" },
              { value: "medium", label: "Medium" },
              { value: "large", label: "Large" },
            ]}
          />
        </div>

        <label className="overlay-settings-row">
          <span>Font size</span>
          <input
            type="range"
            min={12}
            max={20}
            step={1}
            value={settings.fontSize}
            onChange={(e) => set("fontSize", Number(e.target.value))}
          />
          <span className="overlay-settings-value">{settings.fontSize}px</span>
        </label>

        <div className="overlay-settings-row">
          <span>Text density</span>
          <Select
            className="select-overlay"
            value={settings.density}
            onChange={(v: OverlayDensity) => set("density", v)}
            aria-label="Text density"
            options={[
              { value: "compact", label: "Compact" },
              { value: "comfortable", label: "Comfortable" },
            ]}
          />
        </div>

        <label className="overlay-settings-row overlay-settings-checkbox">
          <input
            type="checkbox"
            checked={settings.dragEnabled}
            onChange={(e) => set("dragEnabled", e.target.checked)}
          />
          <span>Enable drag-to-move on header</span>
        </label>

        <label className="overlay-settings-row overlay-settings-checkbox">
          <input type="checkbox" checked={alwaysOnTop} onChange={toggleAlwaysOnTop} />
          <span>Always on top</span>
        </label>
      </div>

      <div className="overlay-settings-section">
        <span className="overlay-settings-label">Screen Capture Protection</span>
        <p>{captureExcluded ? "● Enabled" : "⚠ Unavailable"}</p>
      </div>

      <div className="overlay-settings-section">
        <span className="overlay-settings-label">Hotkeys</span>
        <p>ENTER — Ask</p>
        <p>SHIFT+ENTER — new line while editing</p>
        <p>ESC — hide overlay</p>
      </div>

      <div className="overlay-settings-actions">
        <button className="overlay-button" onClick={resetDefaults}>
          Reset to defaults
        </button>
        <button className="overlay-button primary" onClick={onClose}>
          Close
        </button>
      </div>
    </div>
  );
}
