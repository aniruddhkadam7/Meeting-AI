import { useState } from "react";
import { PerformancePanel } from "./PerformancePanel";

type SettingsSection =
  | "GENERAL"
  | "PERFORMANCE"
  | "AUDIO"
  | "NOTIFICATIONS"
  | "CONTEXT"
  | "PRIVACY"
  | "ABOUT";

const SECTIONS: { key: SettingsSection; label: string }[] = [
  { key: "GENERAL", label: "General" },
  { key: "PERFORMANCE", label: "Performance" },
  { key: "AUDIO", label: "Audio & Microphone" },
  { key: "NOTIFICATIONS", label: "Notifications" },
  { key: "CONTEXT", label: "Context / Documents" },
  { key: "PRIVACY", label: "Privacy" },
  { key: "ABOUT", label: "About / Version" },
];

/// Compact Settings popover reached from the header's gear icon. Performance
/// opens the existing PerformancePanel popover as its own layered overlay
/// (same .popover-overlay/.popover shell as this one) rather than inlining
/// its body, since PerformancePanel already owns its data-fetching and
/// write-action state independently. Other sections are placeholders — no
/// existing screens to reuse for them yet.
export function SettingsPopover({ onClose }: { onClose: () => void }) {
  const [showPerformance, setShowPerformance] = useState(false);
  const [section, setSection] = useState<SettingsSection>("GENERAL");

  if (showPerformance) {
    return <PerformancePanel onClose={() => setShowPerformance(false)} />;
  }

  return (
    <div className="popover-overlay" onMouseDown={(e) => e.target === e.currentTarget && onClose()}>
      <div className="popover" role="dialog" aria-modal="true" aria-label="Settings">
        <div className="popover-header">
          <span className="setup-section-label">Settings</span>
          <button className="modal-close-btn" onClick={onClose} title="Close" aria-label="Close">
            ✕
          </button>
        </div>

        <div className="popover-body settings-popover-body">
          <div className="workspace-nav settings-popover-nav">
            {SECTIONS.map((s) => (
              <button
                key={s.key}
                className={["workspace-nav-item", section === s.key ? "active" : ""].filter(Boolean).join(" ")}
                onClick={() => (s.key === "PERFORMANCE" ? setShowPerformance(true) : setSection(s.key))}
              >
                {s.label}
              </button>
            ))}
          </div>

          <div className="settings-popover-content">
            {section === "GENERAL" && <p className="setup-hint">General settings are coming soon.</p>}
            {section === "AUDIO" && <p className="setup-hint">Audio & microphone settings are coming soon.</p>}
            {section === "NOTIFICATIONS" && <p className="setup-hint">Notification settings are coming soon.</p>}
            {section === "CONTEXT" && (
              <p className="setup-hint">
                Manage documents attached to Interview and Meeting sessions from the Context (📎) button in the
                header.
              </p>
            )}
            {section === "PRIVACY" && (
              <p className="setup-hint">
                Smallbird runs speech-to-text and document search locally on this device. Audio and documents are
                never sent anywhere unless you explicitly sign in for optional cloud sync.
              </p>
            )}
            {section === "ABOUT" && <p className="setup-hint">Smallbird — version 0.1.0</p>}
          </div>
        </div>
      </div>
    </div>
  );
}
