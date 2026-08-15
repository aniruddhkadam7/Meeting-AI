import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import type { AgentConversationEntry } from "./types";

function formatDate(ms: number) {
  return new Date(ms).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function formatTime(ms: number) {
  return new Date(ms).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

function preview(entry: AgentConversationEntry): string {
  return entry.turns[0]?.question || "No conversation recorded.";
}

interface Props {
  agentId: string;
  refreshKey: number;
}

/// This agent's own Conversations/History — stored in a file keyed by
/// agentId (see agents::history in Rust), so it never mixes with another
/// agent's conversations.
export function AgentHistory({ agentId, refreshKey }: Props) {
  const [entries, setEntries] = useState<AgentConversationEntry[]>([]);
  const [selected, setSelected] = useState<AgentConversationEntry | null>(null);

  const refresh = useCallback(async () => {
    try {
      const list = await invoke<AgentConversationEntry[]>("list_agent_history", { agentId });
      setEntries(list);
    } catch {
      setEntries([]);
    }
  }, [agentId]);

  useEffect(() => {
    refresh();
    setSelected(null);
  }, [refresh, refreshKey]);

  const removeEntry = useCallback(
    async (id: string) => {
      try {
        await invoke("delete_agent_history_entry", { agentId, id });
        setSelected((cur) => (cur?.id === id ? null : cur));
        await refresh();
      } catch {
        // Best-effort — the entry stays in the list if deletion fails.
      }
    },
    [agentId, refresh],
  );

  if (selected) {
    return (
      <div className="history-view">
        <div className="history-view-head">
          <button className="link-button" onClick={() => setSelected(null)}>
            ← Back to History
          </button>
          <button className="link-button" onClick={() => removeEntry(selected.id)}>
            Delete
          </button>
        </div>

        <div className="history-view-meta">
          <h1 className="history-view-title">Conversation</h1>
          <p className="history-view-subtitle">
            {formatDate(selected.started_at_ms)} at {formatTime(selected.started_at_ms)}
          </p>
        </div>

        <div className="history-view-transcript" role="log" aria-readonly="true">
          {selected.turns.map((turn, i) => (
            <div key={i} className="history-turn-block">
              <div className="history-turn-q-row">
                <span className="history-turn-tag">You asked</span>
                <p className="history-turn-text">{turn.question}</p>
              </div>
              <div className="history-turn-q-row">
                <span className="history-turn-tag">Answer</span>
                <p className="history-turn-text">{turn.answer}</p>
              </div>
            </div>
          ))}
        </div>
      </div>
    );
  }

  return (
    <div className="history-view">
      <section className="setup-hero">
        <h1 className="setup-title">History</h1>
        <p className="setup-subtitle">Review past conversations with this agent</p>
      </section>

      {entries.length === 0 ? (
        <p className="history-empty">Past conversations will appear here once you start one.</p>
      ) : (
        <div className="history-entries">
          {entries.map((entry) => (
            <button className="history-entry-card" key={entry.id} onClick={() => setSelected(entry)}>
              <div className="history-entry-top">
                <span className="history-entry-title">{entry.turns.length} exchange{entry.turns.length === 1 ? "" : "s"}</span>
              </div>
              <span className="history-entry-when">
                {formatDate(entry.started_at_ms)} at {formatTime(entry.started_at_ms)}
              </span>
              <p className="history-entry-preview">{preview(entry)}</p>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
