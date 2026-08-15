import { useCallback, useState } from "react";
import redlyLogo from "./assets/redly-logo.png";
import { EngagementHistory } from "./EngagementHistory";
import { EngagementSetup } from "./EngagementSetup";

type WorkspaceView = "NEW_SESSION" | "ENGAGEMENTS" | "SETTINGS";

const NAV_ITEMS: { key: WorkspaceView; label: string }[] = [
  { key: "NEW_SESSION", label: "New Session" },
  { key: "ENGAGEMENTS", label: "Engagements" },
  { key: "SETTINGS", label: "Settings" },
];

interface Props {
  onExit: () => void;
}

export function ConsultingWorkspace({ onExit }: Props) {
  const [view, setView] = useState<WorkspaceView>("NEW_SESSION");
  const [historyRefreshKey, setHistoryRefreshKey] = useState(0);
  const [setupKey, setSetupKey] = useState(0);

  const goToNewSession = useCallback(() => {
    setSetupKey((k) => k + 1);
    setView("NEW_SESSION");
  }, []);

  return (
    <div className="workspace-shell">
      <header className="workspace-header">
        <button className="workspace-back-btn" onClick={onExit} title="Back to REDLY home">
          ← Back
        </button>
        <button className="workspace-brand" onClick={onExit} title="Back to REDLY home">
          <img className="workspace-logo" src={redlyLogo} alt="REDLY" />
          <span className="workspace-wordmark">REDLY</span>
        </button>
      </header>

      <div className="workspace-body">
        <nav className="workspace-sidebar">
          <div className="workspace-nav">
            {NAV_ITEMS.map((item) => (
              <button
                key={item.key}
                className={["workspace-nav-item", view === item.key ? "active" : ""]
                  .filter(Boolean)
                  .join(" ")}
                onClick={() => (item.key === "NEW_SESSION" ? goToNewSession() : setView(item.key))}
              >
                {item.label}
              </button>
            ))}
          </div>
        </nav>

        <div className="workspace-main">
          {view === "NEW_SESSION" && (
            <EngagementSetup
              key={setupKey}
              onStart={() => {
                setHistoryRefreshKey((k) => k + 1);
              }}
            />
          )}
          {view === "ENGAGEMENTS" && <EngagementHistory refreshKey={historyRefreshKey} />}
          {view === "SETTINGS" && (
            <div className="workspace-placeholder">
              <h1 className="setup-title">Settings</h1>
              <p className="setup-subtitle">Settings for the Consulting workspace are coming soon.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
