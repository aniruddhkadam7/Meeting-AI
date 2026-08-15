import { useCallback, useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { Button, Card, EmptyState } from "./ui";
import { Agent, PREDEFINED_ROLES } from "./types";

export type AgentAction = "CUSTOMIZE" | "KNOWLEDGE" | "HISTORY";

interface Props {
  onOpen: (agent: Agent, action?: AgentAction) => void;
  onCreateNew: () => void;
  onStart: (agent: Agent) => void;
  refreshKey: number;
}

function roleLabel(agent: Agent): string {
  if (!agent.baseRole) return "Custom Agent";
  return PREDEFINED_ROLES.find((r) => r.value === agent.baseRole)?.label ?? "Custom Agent";
}

/// The agents home: start an agent, jump straight into one of its management
/// actions, or "+ Create Agent". Every action beyond "open the full
/// workspace" is reachable right from the card — no need to enter the
/// workspace just to rename or start a conversation.
export function AgentList({ onOpen, onCreateNew, onStart, refreshKey }: Props) {
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [menuFor, setMenuFor] = useState<string | null>(null);
  const [renaming, setRenaming] = useState<Agent | null>(null);
  const [renameValue, setRenameValue] = useState("");
  const [deleting, setDeleting] = useState<Agent | null>(null);
  const [starting, setStarting] = useState<string | null>(null);
  const menuRef = useRef<HTMLDivElement | null>(null);

  const refresh = useCallback(async () => {
    try {
      const list = await invoke<Agent[]>("list_agents");
      setAgents(list);
    } catch {
      setAgents([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh, refreshKey]);

  useEffect(() => {
    if (!menuFor) return;
    const onDocClick = (e: MouseEvent) => {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuFor(null);
    };
    document.addEventListener("mousedown", onDocClick);
    return () => document.removeEventListener("mousedown", onDocClick);
  }, [menuFor]);

  const startAgent = useCallback(
    async (agent: Agent) => {
      setStarting(agent.id);
      try {
        await onStart(agent);
      } finally {
        setStarting(null);
      }
    },
    [onStart],
  );

  const openRename = useCallback((agent: Agent) => {
    setMenuFor(null);
    setRenaming(agent);
    setRenameValue(agent.name);
  }, []);

  const submitRename = useCallback(async () => {
    if (!renaming) return;
    const name = renameValue.trim();
    if (!name || name === renaming.name) {
      setRenaming(null);
      return;
    }
    try {
      await invoke("update_agent", { input: { id: renaming.id, name } });
      setRenaming(null);
      refresh();
    } catch {
      // Keep the rename dialog open so the user can retry.
    }
  }, [renaming, renameValue, refresh]);

  const confirmDelete = useCallback(async () => {
    if (!deleting) return;
    try {
      await invoke("delete_agent", { id: deleting.id });
    } finally {
      setDeleting(null);
      refresh();
    }
  }, [deleting, refresh]);

  return (
    <div className="setup-shell">
      <section className="setup-hero">
        <div className="setup-hero-text">
          <h1 className="setup-title">Agents</h1>
          <p className="setup-subtitle">Choose an agent, or create a new one</p>
        </div>
        <div className="setup-hero-actions">
          <Button variant="primary" onClick={onCreateNew}>
            + Create Agent
          </Button>
        </div>
      </section>

      {!loading && agents.length === 0 && (
        <Card>
          <EmptyState
            icon="🤖"
            title="No agents yet"
            description="Create your first agent — pick a role, or build a custom one."
          />
        </Card>
      )}

      {agents.length > 0 && (
        <div className="history-entries">
          {agents.map((agent) => (
            <div className="agent-card" key={agent.id}>
              <button className="agent-card-main" onClick={() => onOpen(agent)}>
                <div className="history-entry-top">
                  <span className="history-entry-title">{agent.name}</span>
                </div>
                <span className="history-entry-when">{roleLabel(agent)}</span>
                {agent.description && <p className="history-entry-preview">{agent.description}</p>}
              </button>

              <div className="agent-card-actions">
                <Button variant="primary" size="sm" onClick={() => startAgent(agent)} disabled={starting === agent.id}>
                  {starting === agent.id ? "Starting…" : "Start"}
                </Button>

                <div className="agent-card-menu-wrap" ref={menuFor === agent.id ? menuRef : undefined}>
                  <button
                    className="agent-card-menu-btn"
                    onClick={() => setMenuFor((cur) => (cur === agent.id ? null : agent.id))}
                    title="More actions"
                    aria-label="More actions"
                  >
                    ⋯
                  </button>
                  {menuFor === agent.id && (
                    <div className="agent-card-menu">
                      <button onClick={() => { setMenuFor(null); onOpen(agent, "CUSTOMIZE"); }}>Customize</button>
                      <button onClick={() => { setMenuFor(null); onOpen(agent, "KNOWLEDGE"); }}>Add knowledge</button>
                      <button onClick={() => { setMenuFor(null); onOpen(agent, "HISTORY"); }}>View history</button>
                      <button onClick={() => openRename(agent)}>Rename</button>
                      <button className="danger" onClick={() => { setMenuFor(null); setDeleting(agent); }}>
                        Delete
                      </button>
                    </div>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}

      {renaming && (
        <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && setRenaming(null)}>
          <div className="modal-panel agent-rename-modal" role="dialog" aria-modal="true" aria-label="Rename agent">
            <header className="modal-header">
              <h1 className="setup-title">Rename Agent</h1>
              <button className="modal-close-btn" onClick={() => setRenaming(null)} title="Close" aria-label="Close">
                ✕
              </button>
            </header>
            <div className="modal-body">
              <input
                className="setup-input"
                autoFocus
                value={renameValue}
                onChange={(e) => setRenameValue(e.target.value)}
                onKeyDown={(e) => e.key === "Enter" && submitRename()}
              />
            </div>
            <footer className="modal-footer">
              <Button variant="ghost" onClick={() => setRenaming(null)}>
                Cancel
              </Button>
              <Button variant="primary" onClick={submitRename}>
                Save
              </Button>
            </footer>
          </div>
        </div>
      )}

      {deleting && (
        <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && setDeleting(null)}>
          <div className="modal-panel agent-delete-modal" role="dialog" aria-modal="true" aria-label="Delete agent">
            <header className="modal-header">
              <h1 className="setup-title">Delete "{deleting.name}"?</h1>
              <button className="modal-close-btn" onClick={() => setDeleting(null)} title="Close" aria-label="Close">
                ✕
              </button>
            </header>
            <div className="modal-body">
              <p className="setup-hint">This removes the agent, its instructions, and its conversation history. This can't be undone.</p>
            </div>
            <footer className="modal-footer">
              <Button variant="ghost" onClick={() => setDeleting(null)}>
                Cancel
              </Button>
              <Button variant="danger" onClick={confirmDelete}>
                Delete
              </Button>
            </footer>
          </div>
        </div>
      )}
    </div>
  );
}
