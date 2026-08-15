import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { ConsultingNotesView, type ConsultingNote } from "./ConsultingNotes";

interface ConsultingTurn {
  speaker: "CONSULTANT" | "CLIENT";
  text: string;
}

interface ConsultingSessionEntry {
  id: string;
  started_at_ms: number;
  ended_at_ms: number;
  turns: ConsultingTurn[];
  notes: ConsultingNote;
}

interface Engagement {
  id: string;
  client_name: string;
  project_name: string | null;
  created_at_ms: number;
  sessions: ConsultingSessionEntry[];
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

interface Props {
  refreshKey: number;
}

export function EngagementHistory({ refreshKey }: Props) {
  const [engagements, setEngagements] = useState<Engagement[]>([]);
  const [selectedEngagement, setSelectedEngagement] = useState<Engagement | null>(null);
  const [selectedSession, setSelectedSession] = useState<ConsultingSessionEntry | null>(null);

  const refresh = useCallback(async () => {
    try {
      const list = await invoke<Engagement[]>("list_engagements");
      setEngagements(list);
    } catch {
      setEngagements([]);
    }
  }, []);

  useEffect(() => {
    refresh();
    setSelectedEngagement(null);
    setSelectedSession(null);
  }, [refresh, refreshKey]);

  const removeEngagement = useCallback(
    async (id: string) => {
      try {
        await invoke("delete_engagement", { id });
        setSelectedEngagement((cur) => (cur?.id === id ? null : cur));
        await refresh();
      } catch {
        // Best-effort.
      }
    },
    [refresh],
  );

  if (selectedSession) {
    return (
      <div className="history-view">
        <div className="history-view-head">
          <button className="link-button" onClick={() => setSelectedSession(null)}>
            ← Back to Sessions
          </button>
        </div>
        <div className="history-view-meta">
          <h1 className="history-view-title">Session</h1>
          <p className="history-view-subtitle">
            {formatDate(selectedSession.started_at_ms)} at {formatTime(selectedSession.started_at_ms)} ·{" "}
            {formatDuration(selectedSession.started_at_ms, selectedSession.ended_at_ms)}
          </p>
        </div>

        {selectedSession.notes && <ConsultingNotesView notes={selectedSession.notes} />}

        <div className="history-view-transcript" role="log" aria-readonly="true">
          {selectedSession.turns.length === 0 ? (
            <p className="history-empty">No conversation was recorded in this session.</p>
          ) : (
            selectedSession.turns.map((turn, i) => (
              <div key={i} className="history-turn-block">
                <div className="history-turn-q-row">
                  <span className="history-turn-tag">{turn.speaker === "CLIENT" ? "Client" : "Consultant"}</span>
                  <p className="history-turn-text">{turn.text}</p>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    );
  }

  if (selectedEngagement) {
    return (
      <div className="history-view">
        <div className="history-view-head">
          <button className="link-button" onClick={() => setSelectedEngagement(null)}>
            ← Back to Engagements
          </button>
          <button className="link-button" onClick={() => removeEngagement(selectedEngagement.id)}>
            Delete
          </button>
        </div>
        <div className="history-view-meta">
          <h1 className="history-view-title">
            {[selectedEngagement.client_name, selectedEngagement.project_name].filter(Boolean).join(" · ")}
          </h1>
          <p className="history-view-subtitle">Created {formatDate(selectedEngagement.created_at_ms)}</p>
        </div>

        {selectedEngagement.sessions.length === 0 ? (
          <p className="history-empty">No sessions recorded yet for this engagement.</p>
        ) : (
          <div className="history-entries">
            {selectedEngagement.sessions.map((session) => (
              <button className="history-entry-card" key={session.id} onClick={() => setSelectedSession(session)}>
                <div className="history-entry-top">
                  <span className="history-entry-title">
                    {formatDate(session.started_at_ms)} at {formatTime(session.started_at_ms)}
                  </span>
                  <span className="history-entry-duration">
                    {formatDuration(session.started_at_ms, session.ended_at_ms)}
                  </span>
                </div>
                <p className="history-entry-preview">{session.notes?.summary || "No summary recorded."}</p>
              </button>
            ))}
          </div>
        )}
      </div>
    );
  }

  return (
    <div className="history-view">
      <section className="setup-hero">
        <h1 className="setup-title">Engagements</h1>
        <p className="setup-subtitle">Review your consulting engagements and sessions</p>
      </section>

      {engagements.length === 0 ? (
        <p className="history-empty">Engagements will appear here once you create one.</p>
      ) : (
        <div className="history-entries">
          {engagements.map((eng) => (
            <button className="history-entry-card" key={eng.id} onClick={() => setSelectedEngagement(eng)}>
              <div className="history-entry-top">
                <span className="history-entry-title">
                  {[eng.client_name, eng.project_name].filter(Boolean).join(" · ")}
                </span>
                <span className="history-entry-duration">{eng.sessions.length} session(s)</span>
              </div>
              <span className="history-entry-when">Created {formatDate(eng.created_at_ms)}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
