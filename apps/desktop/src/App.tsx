import { useCallback, useState } from "react";
import "./App.css";
import redlyLogo from "./assets/redly-logo.png";
import { Home } from "./Home";
import { InterviewWorkspace } from "./InterviewWorkspace";
import { SalesWorkspace } from "./SalesWorkspace";
import { ConsultingWorkspace } from "./ConsultingWorkspace";
import { NotesWorkspace } from "./NotesWorkspace";
import { AgentsView } from "./AgentsView";
import { Button } from "./ui";

type View = "HOME" | "INTERVIEW" | "SALES" | "CONSULTING" | "NOTES" | "AGENTS";

function App() {
  const [view, setView] = useState<View>("HOME");
  const [agentsInitialSubview, setAgentsInitialSubview] = useState<"LIST" | "CREATE">("LIST");

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
          <img className="header-logo" src={redlyLogo} alt="REDLY" />
          <div className="header-titles">
            <span className="header-product">REDLY</span>
          </div>
        </div>
      </header>

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
