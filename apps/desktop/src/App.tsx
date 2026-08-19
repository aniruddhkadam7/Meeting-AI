import { useCallback, useState } from "react";
import "./App.css";
import whitedotaiLogo from "./assets/whitedotai-logo.png";
import { Home } from "./Home";
import { InterviewWorkspace } from "./InterviewWorkspace";
import { SalesWorkspace } from "./SalesWorkspace";
import { ConsultingWorkspace } from "./ConsultingWorkspace";
import { NotesWorkspace } from "./NotesWorkspace";
import { AgentsView } from "./AgentsView";
import { Account } from "./Account";
import { PerformancePanel } from "./PerformancePanel";
import { UpdateBanner } from "./UpdateBanner";
import { Button } from "./ui";

type View = "HOME" | "INTERVIEW" | "SALES" | "CONSULTING" | "NOTES" | "AGENTS";

function App() {
  const [view, setView] = useState<View>("HOME");
  const [agentsInitialSubview, setAgentsInitialSubview] = useState<"LIST" | "CREATE">("LIST");
  const [showAccount, setShowAccount] = useState(false);
  const [showPerformance, setShowPerformance] = useState(false);

  const goHome = useCallback(() => {
    setView("HOME");
  }, []);

  if (view === "INTERVIEW") {
    return (
      <main className="app-shell app-shell-workspace">
        <InterviewWorkspace onExit={goHome} />
      </main>
    );
  }

  if (view === "SALES") {
    return (
      <main className="app-shell app-shell-workspace">
        <SalesWorkspace onExit={goHome} />
      </main>
    );
  }

  if (view === "CONSULTING") {
    return (
      <main className="app-shell app-shell-workspace">
        <ConsultingWorkspace onExit={goHome} />
      </main>
    );
  }

  if (view === "NOTES") {
    return (
      <main className="app-shell app-shell-workspace">
        <NotesWorkspace onExit={goHome} />
      </main>
    );
  }

  if (view === "AGENTS") {
    return (
      <main className="app-shell app-shell-workspace">
        <AgentsView onExit={goHome} initialSubview={agentsInitialSubview} />
      </main>
    );
  }

  return (
    <main className="app-shell">
      <header className="header">
        <div className="header-brand">
          {view !== "HOME" && (
            <Button variant="ghost" size="sm" onClick={goHome} aria-label="Back to home">
              ←
            </Button>
          )}
          <img className="header-logo" src={whitedotaiLogo} alt="WhitedotAI" />
          <div className="header-titles">
            <span className="header-product">WhitedotAI</span>
          </div>
        </div>
        <Button variant="ghost" size="sm" onClick={() => setShowPerformance(true)}>
          Performance
        </Button>
        <Button variant="ghost" size="sm" onClick={() => setShowAccount(true)}>
          Account
        </Button>
      </header>

      {showAccount && <Account onClose={() => setShowAccount(false)} />}
      {showPerformance && <PerformancePanel onClose={() => setShowPerformance(false)} />}
      <UpdateBanner />

      <Home
        onSelectInterview={() => setView("INTERVIEW")}
        onSelectSales={() => setView("SALES")}
        onSelectAgents={() => {
          setAgentsInitialSubview("LIST");
          setView("AGENTS");
        }}
        onCreateAgent={() => {
          setAgentsInitialSubview("CREATE");
          setView("AGENTS");
        }}
      />
    </main>
  );
}

export default App;
