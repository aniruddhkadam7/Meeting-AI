import { invoke } from "@tauri-apps/api/core";
import {
  AgentOverlaySettings,
  DEFAULT_AGENT_OVERLAY_SETTINGS,
  SIZE_FRACTIONS,
  type AnswerDisplay,
  type OverlayDensity,
  type OverlaySize,
} from "./agentOverlaySettings";

interface Props {
  agentId: string;
  settings: AgentOverlaySettings;
  onChange: (settings: AgentOverlaySettings) => void;
  onClose: () => void;
}

/// This agent's own overlay Settings panel — position/size/answer display/
/// auto AI, kept separate per agent. Mirrors OverlaySettingsPanel.tsx
/// (Interview Mode) so switching between Interview Mode and an agent's live
/// overlay feels like the same interface, minus the interview-specific
/// role/company/job-description fields agents don't need.
export function AgentOverlaySettingsPanel({ agentId, settings, onChange, onClose }: Props) {
  const set = <K extends keyof AgentOverlaySettings>(key: K, value: AgentOverlaySettings[K]) => {
    onChange({ ...settings, [key]: value });
  };

  const changeSize = (size: OverlaySize) => {
    set("size", size);
    invoke("resize_agent_overlay", { agentId, fraction: SIZE_FRACTIONS[size] }).catch(() => {
      // Best-effort — the CSS size-* class still applies even if the actual
      // OS window resize fails.
    });
  };

  const resetDefaults = () => onChange({ ...DEFAULT_AGENT_OVERLAY_SETTINGS });

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
          <select value={settings.size} onChange={(e) => changeSize(e.target.value as OverlaySize)}>
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
          <select value={settings.density} onChange={(e) => set("density", e.target.value as OverlayDensity)}>
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
      </div>

      <div className="overlay-settings-section">
        <span className="overlay-settings-label">Answer</span>

        <label className="overlay-settings-row overlay-settings-checkbox">
          <input type="checkbox" checked={settings.autoAI} onChange={(e) => set("autoAI", e.target.checked)} />
          <span>Auto AI — send a question automatically once you stop talking</span>
        </label>

        <label className="overlay-settings-row">
          <span>Answer display</span>
          <select
            value={settings.answerDisplay}
            onChange={(e) => set("answerDisplay", e.target.value as AnswerDisplay)}
          >
            <option value="chat">Chat (full conversation)</option>
            <option value="compact">Compact (latest answer only)</option>
          </select>
        </label>

        <p className="overlay-settings-note">
          Response length, style, and format for this agent are set from its Personalization tab.
        </p>
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
