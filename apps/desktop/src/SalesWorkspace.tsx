import { useCallback, useState } from "react";
import redlyLogo from "./assets/redly-logo.png";
import { SalesHistory } from "./SalesHistory";
import { SalesSetup } from "./SalesSetup";

type WorkspaceView = "NEW_CALL" | "HISTORY" | "SETTINGS";

const NAV_ITEMS: { key: WorkspaceView; label: string }[] = [
  { key: "NEW_CALL", label: "New Call" },
  { key: "HISTORY", label: "History" },
  { key: "SETTINGS", label: "Settings" },
];

interface Props {
  onExit: () => void;
}

export function SalesWorkspace({ onExit }: Props) {
  const [view, setView] = useState<WorkspaceView>("NEW_CALL");
  const [historyRefreshKey, setHistoryRefreshKey] = useState(0);
  const [setupKey, setSetupKey] = useState(0);

  const goToNewCall = useCallback(() => {
    setSetupKey((k) => k + 1);
    setView("NEW_CALL");
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
                onClick={() => (item.key === "NEW_CALL" ? goToNewCall() : setView(item.key))}
              >
                {item.label}
              </button>
            ))}
          </div>
        </nav>

        <div className="workspace-main">
          {view === "NEW_CALL" && (
            <SalesSetup
              key={setupKey}
              onStart={() => {
                setHistoryRefreshKey((k) => k + 1);
              }}
            />
          )}
          {view === "HISTORY" && <SalesHistory refreshKey={historyRefreshKey} />}
          {view === "SETTINGS" && (
            <div className="workspace-placeholder">
              <h1 className="setup-title">Settings</h1>
              <p className="setup-subtitle">Settings for the Sales workspace are coming soon.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
