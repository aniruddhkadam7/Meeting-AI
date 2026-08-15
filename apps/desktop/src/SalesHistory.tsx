import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { SalesSummaryView, type SalesCallSummary } from "./SalesSummary";

interface SalesTurn {
  speaker: "REP" | "CUSTOMER";
  text: string;
}

interface SalesHistoryEntry {
  id: string;
  started_at_ms: number;
  ended_at_ms: number;
  customer_name: string | null;
  company_name: string | null;
  turns: SalesTurn[];
  summary: SalesCallSummary;
}

function formatDate(ms: number) {
  return new Date(ms).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

function formatTime(ms: number) {
  return new Date(ms).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

function formatDuration(startMs: number, endMs: number) {
  const totalSeconds = Math.max(0, Math.round((endMs - startMs) / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes === 0) return `${seconds}s`;
  return `${minutes}m ${seconds}s`;
}

function preview(entry: SalesHistoryEntry): string {
  return entry.summary?.summary || entry.turns[0]?.text || "No conversation recorded.";
}

interface Props {
  refreshKey: number;
}

export function SalesHistory({ refreshKey }: Props) {
  const [entries, setEntries] = useState<SalesHistoryEntry[]>([]);
  const [selected, setSelected] = useState<SalesHistoryEntry | null>(null);

  const refresh = useCallback(async () => {
    try {
      const list = await invoke<SalesHistoryEntry[]>("list_sales_history");
      setEntries(list);
    } catch {
      setEntries([]);
    }
  }, []);

  useEffect(() => {
    refresh();
    setSelected(null);
  }, [refresh, refreshKey]);

  const removeEntry = useCallback(
    async (id: string) => {
      try {
        await invoke("delete_sales_history_entry", { id });
        setSelected((cur) => (cur?.id === id ? null : cur));
        await refresh();
      } catch {
        // Best-effort — the entry stays in the list if deletion fails.
      }
    },
    [refresh],
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
          <h1 className="history-view-title">
            {selected.customer_name || selected.company_name
              ? [selected.customer_name, selected.company_name].filter(Boolean).join(" · ")
              : "Sales Call"}
          </h1>
          <p className="history-view-subtitle">
            {formatDate(selected.started_at_ms)} at {formatTime(selected.started_at_ms)} ·{" "}
            {formatDuration(selected.started_at_ms, selected.ended_at_ms)}
          </p>
        </div>

        {selected.summary && <SalesSummaryView summary={selected.summary} />}

        <div className="history-view-transcript" role="log" aria-readonly="true">
          {selected.turns.length === 0 ? (
            <p className="history-empty">No conversation was recorded in this call.</p>
          ) : (
            selected.turns.map((turn, i) => (
              <div key={i} className="history-turn-block">
                <div className="history-turn-q-row">
                  <span className="history-turn-tag">{turn.speaker === "CUSTOMER" ? "Customer" : "Rep"}</span>
                  <p className="history-turn-text">{turn.text}</p>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    );
  }

  return (
    <div className="history-view">
      <section className="setup-hero">
        <h1 className="setup-title">History</h1>
        <p className="setup-subtitle">Review your past sales calls</p>
      </section>

      {entries.length === 0 ? (
        <p className="history-empty">Past calls will appear here once you complete one.</p>
      ) : (
        <div className="history-entries">
          {entries.map((entry) => (
            <button className="history-entry-card" key={entry.id} onClick={() => setSelected(entry)}>
              <div className="history-entry-top">
                <span className="history-entry-title">
                  {entry.customer_name || entry.company_name
                    ? [entry.customer_name, entry.company_name].filter(Boolean).join(" · ")
                    : "Sales Call"}
                </span>
                <span className="history-entry-duration">
                  {formatDuration(entry.started_at_ms, entry.ended_at_ms)}
                </span>
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
