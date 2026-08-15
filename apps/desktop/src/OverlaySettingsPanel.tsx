import { invoke } from "@tauri-apps/api/core";
import { useState } from "react";
import {
  DEFAULT_OVERLAY_SETTINGS,
  SIZE_FRACTIONS,
  type AnswerLength,
  type OverlayDensity,
  type OverlaySettings,
  type OverlaySize,
  type ResponseStyle,
} from "./overlaySettings";

interface Props {
  settings: OverlaySettings;
  onChange: (settings: OverlaySettings) => void;
  onClose: () => void;
  captureExcluded: boolean | null;
}

/// Interview Mode's Settings panel — everything the overlay needs beyond the
/// question/answer flow, without becoming the large Record/Prepare
/// dashboard. Renders inline in the same small overlay window (swapped in for
/// the question/answer body), not a separate window.
export function OverlaySettingsPanel({ settings, onChange, onClose, captureExcluded }: Props) {
  const [alwaysOnTop, setAlwaysOnTop] = useState(true);

  const set = <K extends keyof OverlaySettings>(key: K, value: OverlaySettings[K]) => {
    onChange({ ...settings, [key]: value });
  };

  const changeSize = (size: OverlaySize) => {
    set("size", size);
    invoke("resize_interview_overlay", { fraction: SIZE_FRACTIONS[size] }).catch(() => {
      // Best-effort — the CSS size-* class still applies even if the actual
      // OS window resize fails, so the panel remains usable either way.
    });
  };

  const toggleAlwaysOnTop = () => {
    const next = !alwaysOnTop;
    setAlwaysOnTop(next);
    invoke("set_overlay_always_on_top", { enabled: next }).catch(() => {
      // Best-effort — the window remains on top by default even if this call
      // fails, so there is nothing actionable to show the user here.
    });
  };

  const resetDefaults = () => onChange({ ...DEFAULT_OVERLAY_SETTINGS });

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

        <label className="overlay-settings-row">
          <span>Overlay size</span>
          <select
            value={settings.size}
            onChange={(e) => changeSize(e.target.value as OverlaySize)}
          >
            <option value="small">Small</option>
            <option value="medium">Medium</option>
            <option value="large">Large</option>
          </select>
        </label>

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

        <label className="overlay-settings-row">
          <span>Text density</span>
          <select
            value={settings.density}
            onChange={(e) => set("density", e.target.value as OverlayDensity)}
          >
            <option value="compact">Compact</option>
            <option value="comfortable">Comfortable</option>
          </select>
        </label>

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
        <span className="overlay-settings-label">Answer</span>

        <label className="overlay-settings-row overlay-settings-checkbox">
          <input
            type="checkbox"
            checked={settings.autoAI}
            onChange={(e) => set("autoAI", e.target.checked)}
          />
          <span>Auto AI — send a question automatically once you stop talking</span>
        </label>

        <label className="overlay-settings-row">
          <span>Answer length</span>
          <select
            value={settings.answerLength}
            onChange={(e) => set("answerLength", e.target.value as AnswerLength)}
          >
            <option value="brief">Brief (1-3 sentences)</option>
            <option value="default">Default (~50-120 words)</option>
            <option value="detailed">Detailed</option>
          </select>
        </label>

        <label className="overlay-settings-row">
          <span>Response style</span>
          <select
            value={settings.responseStyle}
            onChange={(e) => set("responseStyle", e.target.value as ResponseStyle)}
          >
            <option value="natural">Natural</option>
            <option value="technical">Technical</option>
            <option value="concise">Concise</option>
          </select>
        </label>

        <label className="overlay-settings-row overlay-settings-column">
          <span>Role (optional)</span>
          <input
            type="text"
            value={settings.role}
            onChange={(e) => set("role", e.target.value)}
            placeholder="e.g. Senior Backend Engineer"
          />
        </label>

        <label className="overlay-settings-row overlay-settings-column">
          <span>Job description (optional)</span>
          <textarea
            value={settings.jobDescription}
            onChange={(e) => set("jobDescription", e.target.value)}
            placeholder="Paste relevant job description context…"
            rows={3}
          />
        </label>
      </div>

      <div className="overlay-settings-section">
        <span className="overlay-settings-label">Speech Recognition</span>

        <label className="overlay-settings-row">
          <span>STT sensitivity</span>
          <input
            type="range"
            min={0}
            max={100}
            step={5}
            value={settings.sttSensitivity}
            onChange={(e) => set("sttSensitivity", Number(e.target.value))}
          />
        </label>
        <p className="overlay-settings-note">
          Higher sensitivity finalizes questions sooner after a pause; lower waits longer.
        </p>
      </div>

      <div className="overlay-settings-section">
        <span className="overlay-settings-label">Screen Capture Protection</span>
        <p>{captureExcluded ? "● Enabled" : "⚠ Unavailable"}</p>
      </div>

      <div className="overlay-settings-section">
        <span className="overlay-settings-label">Hotkeys</span>
        <p>ENTER — Ask AI</p>
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
