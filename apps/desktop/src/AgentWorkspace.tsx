import { useCallback, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import redlyLogo from "./assets/redly-logo.png";
import { Agent, AgentPersonalization } from "./types";
import { Button } from "./ui";
import { PersonalizationEditor } from "./AgentCreate";
import { AgentKnowledgePanel } from "./AgentKnowledgePanel";
import { AgentHistory } from "./AgentHistory";
import { startAgentConversation } from "./agentStart";
import { syncAgentsInBackground } from "./cloudSync";

type WorkspaceView = "KNOWLEDGE" | "HISTORY" | "INSTRUCTIONS" | "PERSONALIZATION";

const NAV_ITEMS: { key: WorkspaceView; label: string }[] = [
  { key: "KNOWLEDGE", label: "Knowledge" },
  { key: "HISTORY", label: "Conversations" },
  { key: "INSTRUCTIONS", label: "Instructions" },
  { key: "PERSONALIZATION", label: "Personalization" },
];

interface Props {
  agent: Agent;
  onExit: () => void;
  onAgentUpdated: (agent: Agent) => void;
  initialView?: WorkspaceView;
}

/// One agent's persistent workspace — Knowledge / Conversations / History /
/// Instructions / Personalization — plus Start Conversation, which opens the
/// same live overlay every agent uses (agents::overlay in Rust, parameterized
/// by this agent's id).
export function AgentWorkspace({ agent, onExit, onAgentUpdated, initialView = "KNOWLEDGE" }: Props) {
  const [view, setView] = useState<WorkspaceView>(initialView);
  const [historyRefreshKey] = useState(0);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const startConversation = useCallback(async () => {
    setError(null);
    setStarting(true);
    try {
      await startAgentConversation(agent);
    } catch (e) {
      setError(String(e));
    } finally {
      setStarting(false);
    }
  }, [agent]);

  return (
    <div className="workspace-shell">
      <header className="workspace-header">
        <button className="workspace-back-btn" onClick={onExit} title="Back to Agents">
          ← Back
        </button>
        <button className="workspace-brand" onClick={onExit} title="Back to REDLY home">
          <img className="workspace-logo" src={redlyLogo} alt="REDLY" />
          <span className="workspace-wordmark">REDLY</span>
        </button>
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 12 }}>
          {error && <span className="error-text">{error}</span>}
          <Button variant="primary" onClick={startConversation} disabled={starting}>
            {starting ? "Starting…" : "Start Conversation"}
          </Button>
        </div>
      </header>

      <div className="workspace-body">
        <nav className="workspace-sidebar">
          <div className="workspace-nav-header">
            <span className="setup-title" style={{ fontSize: "1.1rem" }}>
              {agent.name}
            </span>
          </div>
          <div className="workspace-nav">
            {NAV_ITEMS.map((item) => (
              <button
                key={item.key}
                className={["workspace-nav-item", view === item.key ? "active" : ""].filter(Boolean).join(" ")}
                onClick={() => setView(item.key)}
              >
                {item.label}
              </button>
            ))}
          </div>
        </nav>

        <div className="workspace-main">
          {view === "KNOWLEDGE" && <AgentKnowledgePanel agentId={agent.id} />}
          {view === "HISTORY" && <AgentHistory agentId={agent.id} refreshKey={historyRefreshKey} />}
          {view === "INSTRUCTIONS" && (
            <InstructionsPanel agent={agent} onAgentUpdated={onAgentUpdated} />
          )}
          {view === "PERSONALIZATION" && (
            <PersonalizationPanel agent={agent} onAgentUpdated={onAgentUpdated} />
          )}
        </div>
      </div>
    </div>
  );
}

function InstructionsPanel({ agent, onAgentUpdated }: { agent: Agent; onAgentUpdated: (a: Agent) => void }) {
  const [description, setDescription] = useState(agent.description ?? "");
  const [customInstructions, setCustomInstructions] = useState(agent.customInstructions ?? "");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = useCallback(async () => {
    setSaving(true);
    setError(null);
    try {
      const updated = await invoke<Agent>("update_agent", {
        input: {
          id: agent.id,
          description: description.trim() || null,
          customInstructions: customInstructions.trim() || null,
        },
      });
      onAgentUpdated(updated);
      syncAgentsInBackground();
    } catch (e) {
      setError(String(e));
    } finally {
      setSaving(false);
    }
  }, [agent.id, description, customInstructions, onAgentUpdated]);

  return (
    <div className="setup-shell">
      <section className="setup-hero">
        <div className="setup-hero-text">
          <h1 className="setup-title">Instructions</h1>
          <p className="setup-subtitle">What this agent is for, in plain language</p>
        </div>
        <div className="setup-hero-actions">
          <Button variant="primary" onClick={save} disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </Button>
        </div>
      </section>
      {error && <p className="error">{error}</p>}

      <div className="setup-section" style={{ maxWidth: 560 }}>
        <div className="setup-section-head">
          <span className="setup-section-label">What this agent helps with</span>
          <span className="setup-section-optional">Optional</span>
        </div>
        <div className="setup-section-body">
          <textarea
            className="setup-input"
            rows={2}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="e.g. Helps close enterprise renewal deals"
          />
        </div>
      </div>

      <div className="setup-section" style={{ maxWidth: 560 }}>
        <div className="setup-section-head">
          <span className="setup-section-label">Custom Instructions</span>
          <span className="setup-section-optional">Optional</span>
        </div>
        <div className="setup-section-body">
          <textarea
            className="setup-input"
            rows={4}
            value={customInstructions}
            onChange={(e) => setCustomInstructions(e.target.value)}
            placeholder="Any extra guidance for this agent."
          />
        </div>
      </div>
    </div>
  );
}

function PersonalizationPanel({ agent, onAgentUpdated }: { agent: Agent; onAgentUpdated: (a: Agent) => void }) {
  const [value, setValue] = useState<AgentPersonalization>(agent.personalization);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const save = useCallback(
    async (next: AgentPersonalization) => {
      setValue(next);
      setSaving(true);
      setError(null);
      try {
        const updated = await invoke<Agent>("update_agent", {
          input: { id: agent.id, personalization: next },
        });
        onAgentUpdated(updated);
        syncAgentsInBackground();
      } catch (e) {
        setError(String(e));
      } finally {
        setSaving(false);
      }
    },
    [agent.id, onAgentUpdated],
  );

  return (
    <div className="setup-shell">
      <section className="setup-hero">
        <div className="setup-hero-text">
          <h1 className="setup-title">Personalization</h1>
          <p className="setup-subtitle">{saving ? "Saving…" : "Changes save automatically"}</p>
        </div>
      </section>
      {error && <p className="error">{error}</p>}
      <PersonalizationEditor value={value} onChange={save} />
    </div>
  );
}
