import { useCallback, useState } from "react";
import redlyLogo from "./assets/redly-logo.png";
import { InterviewHistory } from "./InterviewHistory";
import { InterviewSetup } from "./InterviewSetup";

type WorkspaceView = "NEW_INTERVIEW" | "HISTORY" | "SETTINGS";

const NAV_ITEMS: { key: WorkspaceView; label: string }[] = [
  { key: "NEW_INTERVIEW", label: "New Interview" },
  { key: "HISTORY", label: "History" },
  { key: "SETTINGS", label: "Settings" },
];

interface Props {
  onExit: () => void;
}

export function InterviewWorkspace({ onExit }: Props) {
  const [view, setView] = useState<WorkspaceView>("NEW_INTERVIEW");
  const [historyRefreshKey, setHistoryRefreshKey] = useState(0);

  // A fresh key forces InterviewSetup to remount with entirely empty local
  // state — role/company/documents/text — so a session never carries
  // anything over from whatever the user typed before their last interview.
  const [setupKey, setSetupKey] = useState(0);

  const goToNewInterview = useCallback(() => {
    setSetupKey((k) => k + 1);
    setView("NEW_INTERVIEW");
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
                onClick={() => (item.key === "NEW_INTERVIEW" ? goToNewInterview() : setView(item.key))}
              >
                {item.label}
              </button>
            ))}
          </div>
        </nav>

        <div className="workspace-main">
          {view === "NEW_INTERVIEW" && (
            <InterviewSetup
              key={setupKey}
              onStart={() => {
                setHistoryRefreshKey((k) => k + 1);
              }}
            />
          )}
          {view === "HISTORY" && <InterviewHistory refreshKey={historyRefreshKey} />}
          {view === "SETTINGS" && (
            <div className="workspace-placeholder">
              <h1 className="setup-title">Settings</h1>
              <p className="setup-subtitle">Settings for the Interview workspace are coming soon.</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
