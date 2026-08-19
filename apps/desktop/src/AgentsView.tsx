import { useCallback, useState } from "react";
import whitedotaiLogo from "./assets/whitedotai-logo.png";
import { Agent } from "./types";
import { AgentList, AgentAction } from "./AgentList";
import { AgentCreateModal } from "./AgentCreateModal";
import { AgentWorkspace } from "./AgentWorkspace";
import { startAgentConversation } from "./agentStart";

type WorkspaceView = "KNOWLEDGE" | "HISTORY" | "INSTRUCTIONS" | "PERSONALIZATION";

const ACTION_TO_VIEW: Record<AgentAction, WorkspaceView> = {
  CUSTOMIZE: "INSTRUCTIONS",
  KNOWLEDGE: "KNOWLEDGE",
  HISTORY: "HISTORY",
};

type AgentsSubview = "LIST" | { workspace: Agent; initialView: WorkspaceView };

interface Props {
  onExit: () => void;
  /// "CREATE" opens the create-agent modal immediately instead of landing on
  /// the list first — used by Home's own "+ Create Agent" button.
  initialSubview?: "LIST" | "CREATE";
}

/// Top-level Custom Agents flow: a single Agents list (start / customize /
/// add knowledge / view history / rename / delete right from each card), a
/// one-modal creation flow, and a per-agent workspace for anything that
/// needs more room (Knowledge, Conversations, Instructions, Personalization).
export function AgentsView({ onExit, initialSubview = "LIST" }: Props) {
  const [subview, setSubview] = useState<AgentsSubview>("LIST");
  const [showCreate, setShowCreate] = useState(initialSubview === "CREATE");
  const [listRefreshKey, setListRefreshKey] = useState(0);
  const [startError, setStartError] = useState<string | null>(null);

  const openAgent = useCallback(
    (agent: Agent, action?: AgentAction) =>
      setSubview({ workspace: agent, initialView: action ? ACTION_TO_VIEW[action] : "KNOWLEDGE" }),
    [],
  );

  const onCreated = useCallback((agent: Agent) => {
    setShowCreate(false);
    setListRefreshKey((k) => k + 1);
    setSubview({ workspace: agent, initialView: "KNOWLEDGE" });
  }, []);

  const onAgentUpdated = useCallback(
    (agent: Agent) => {
      setSubview((cur) => (typeof cur === "object" ? { ...cur, workspace: agent } : cur));
    },
    [],
  );

  const onStart = useCallback(async (agent: Agent) => {
    setStartError(null);
    try {
      await startAgentConversation(agent);
    } catch (e) {
      setStartError(String(e));
    }
  }, []);

  if (typeof subview === "object") {
    return (
      <AgentWorkspace
        agent={subview.workspace}
        initialView={subview.initialView}
        onExit={() => {
          setListRefreshKey((k) => k + 1);
          setSubview("LIST");
        }}
        onAgentUpdated={onAgentUpdated}
      />
    );
  }

  return (
    <div className="workspace-shell">
      <header className="workspace-header">
        <button className="workspace-back-btn" onClick={onExit} title="Back to WhitedotAI home">
          ← Back
        </button>
        <button className="workspace-brand" onClick={onExit} title="Back to WhitedotAI home">
          <img className="workspace-logo" src={whitedotaiLogo} alt="WhitedotAI" />
          <span className="workspace-wordmark">WhitedotAI</span>
        </button>
      </header>
      <div className="workspace-body">
        <div className="workspace-main">
          {startError && <p className="error">{startError}</p>}
          <AgentList onOpen={openAgent} onCreateNew={() => setShowCreate(true)} onStart={onStart} refreshKey={listRefreshKey} />
        </div>
      </div>

      {showCreate && <AgentCreateModal onCreated={onCreated} onClose={() => setShowCreate(false)} />}
    </div>
  );
}
