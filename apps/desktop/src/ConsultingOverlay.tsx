import { useCallback, useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { getCurrentWebviewWindow } from "@tauri-apps/api/webviewWindow";
import ReactMarkdown from "react-markdown";
import type { TranscriptSegment } from "./types";
import { ConsultingNotesView, type ConsultingNote } from "./ConsultingNotes";

interface OverlayCaptureStatus {
  excluded: boolean;
}

interface Turn {
  id: string;
  question: string;
  answer: string;
  pending: boolean;
  failed?: boolean;
}

interface TranscriptEntry {
  id: string;
  speaker: "Client" | "Consultant";
  text: string;
}

type TrackedKind = "RISK" | "ASSUMPTION" | "DECISION" | "DEPENDENCY" | "ACTION_ITEM";

interface ActiveEngagementInfo {
  engagementId: string;
  clientName: string;
  projectName: string;
  context: string;
}

const overlayWindow = getCurrentWebviewWindow();

const TRACKED_COLUMNS: { kind: TrackedKind; label: string; ownerField?: boolean }[] = [
  { kind: "RISK", label: "Risks" },
  { kind: "ASSUMPTION", label: "Assumptions" },
  { kind: "DECISION", label: "Decisions" },
  { kind: "DEPENDENCY", label: "Dependencies" },
  { kind: "ACTION_ITEM", label: "Action Items", ownerField: true },
];

function loadActiveEngagement(): ActiveEngagementInfo {
  try {
    const raw = window.localStorage.getItem("consulting-mode:active-engagement");
    if (!raw) return { engagementId: "", clientName: "", projectName: "", context: "" };
    const parsed = JSON.parse(raw);
    return {
      engagementId: parsed.engagementId || "",
      clientName: parsed.clientName || "",
      projectName: parsed.projectName || "",
      context: parsed.context || "",
    };
  } catch {
    return { engagementId: "", clientName: "", projectName: "", context: "" };
  }
}

export function ConsultingOverlay() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [captureExcluded, setCaptureExcluded] = useState<boolean | null>(null);
  const [confirmingClose, setConfirmingClose] = useState(false);
  const [transcript, setTranscript] = useState<TranscriptEntry[]>([]);
  const [tracked, setTracked] = useState<Record<TrackedKind, string[]>>({
    RISK: [],
    ASSUMPTION: [],
    DECISION: [],
    DEPENDENCY: [],
    ACTION_ITEM: [],
  });
  const [quickEntry, setQuickEntry] = useState<Record<TrackedKind, string>>({
    RISK: "",
    ASSUMPTION: "",
    DECISION: "",
    DEPENDENCY: "",
    ACTION_ITEM: "",
  });
  const [quickOwner, setQuickOwner] = useState("");
  const [notes, setNotes] = useState<ConsultingNote | null>(null);
  const [ending, setEnding] = useState(false);

  const questionRef = useRef<HTMLTextAreaElement | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const busyRef = useRef(false);
  const sessionStartedAtRef = useRef(Date.now());
  const engagementRef = useRef<ActiveEngagementInfo>(loadActiveEngagement());
  const rawTurnsRef = useRef<{ speaker: "CONSULTANT" | "CLIENT"; text: string }[]>([]);

  useEffect(() => {
    invoke<OverlayCaptureStatus>("show_consulting_overlay")
      .then((status) => setCaptureExcluded(status.excluded))
      .catch((e) => setError(String(e)));

    invoke("start_system_audio_capture").catch((e) => {
      if (String(e) !== "capture already running") {
        setError(`Could not start audio capture: ${String(e)}`);
      }
    });
  }, []);

  useEffect(() => {
    const unlistenTranscript = listen<TranscriptSegment>("transcript:update", (event) => {
      const segment = event.payload;
      const speaker = segment.source === "SYSTEM_AUDIO" ? "Client" : "Consultant";
      if (segment.final_text) {
        setTranscript((prev) => [
          ...prev.slice(-49),
          { id: segment.id, speaker, text: segment.final_text as string },
        ]);
        rawTurnsRef.current.push({
          speaker: speaker === "Client" ? "CLIENT" : "CONSULTANT",
          text: segment.final_text,
        });
      }
    });

    const unlistenDelta = listen<string>("consulting-mode:answer-delta", (event) => {
      setTurns((prev) => {
        if (!prev.length) return prev;
        const last = prev[prev.length - 1];
        if (!last.pending) return prev;
        return [...prev.slice(0, -1), { ...last, answer: last.answer + event.payload }];
      });
    });

    const unlistenComplete = listen<string>("consulting-mode:answer-complete", (event) => {
      setTurns((prev) => {
        if (!prev.length) return prev;
        const last = prev[prev.length - 1];
        if (!last.pending) return prev;
        return [...prev.slice(0, -1), { ...last, answer: event.payload || last.answer, pending: false }];
      });
      busyRef.current = false;
      setBusy(false);
    });

    return () => {
      unlistenTranscript.then((f) => f());
      unlistenDelta.then((f) => f());
      unlistenComplete.then((f) => f());
    };
  }, []);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [turns, transcript]);

  const askAI = useCallback(async () => {
    const trimmed = question.trim();
    if (!trimmed || busyRef.current) return;

    setError(null);
    const turn: Turn = {
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      question: trimmed,
      answer: "",
      pending: true,
    };
    setTurns((prev) => [...prev, turn]);
    setQuestion("");
    busyRef.current = true;
    setBusy(true);

    const history = turns
      .filter((t) => !t.pending && t.answer.trim() && !t.failed)
      .map((t) => ({ question: t.question, answer: t.answer }));

    try {
      const info = engagementRef.current;
      await invoke<string>("ask_consulting_question", {
        question: trimmed,
        history,
        options: {
          answerLength: "default",
          responseStyle: "natural",
          clientName: info.clientName || null,
          projectName: info.projectName || null,
          engagementContext: info.context || null,
        },
      });
    } catch (e) {
      setError(String(e));
      setTurns((prev) => prev.map((t) => (t.id === turn.id ? { ...t, pending: false, failed: true } : t)));
      busyRef.current = false;
      setBusy(false);
    }
  }, [question, turns]);

  const handleQuestionKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        askAI();
      }
    },
    [askAI],
  );

  const addTracked = useCallback(
    async (kind: TrackedKind) => {
      const raw = quickEntry[kind].trim();
      if (!raw) return;
      const text = kind === "ACTION_ITEM" && quickOwner.trim() ? `${quickOwner.trim()}: ${raw}` : raw;
      try {
        await invoke("track_consulting_item", { kind, text });
        setTracked((prev) => ({ ...prev, [kind]: [...prev[kind], text] }));
        setQuickEntry((prev) => ({ ...prev, [kind]: "" }));
        if (kind === "ACTION_ITEM") setQuickOwner("");
      } catch (e) {
        setError(String(e));
      }
    },
    [quickEntry, quickOwner],
  );

  const closeOverlay = useCallback(async () => {
    setConfirmingClose(false);
    invoke("hide_consulting_overlay").catch(() => overlayWindow.hide());
  }, []);

  const endSession = useCallback(async () => {
    setEnding(true);
    setError(null);
    try {
      await invoke("stop_audio_capture").catch(() => {});
      const info = engagementRef.current;
      const result = await invoke<ConsultingNote>("end_consulting_session", {
        turns: rawTurnsRef.current,
        clientName: info.clientName || null,
        projectName: info.projectName || null,
      });
      setNotes(result);
      try {
        await invoke("archive_consulting_session", {
          engagementId: info.engagementId,
          startedAtMs: sessionStartedAtRef.current,
          turns: rawTurnsRef.current,
          notes: result,
        });
      } catch (e) {
        console.error("Failed to archive consulting session:", e);
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setEnding(false);
    }
  }, []);

  const requestClose = useCallback(() => {
    const hasConversation = turns.length > 0 || rawTurnsRef.current.length > 0;
    if (hasConversation && !notes) {
      setConfirmingClose(true);
    } else {
      closeOverlay();
    }
  }, [turns, notes, closeOverlay]);

  const hasConversation = turns.length > 0;

  if (notes) {
    return (
      <div className="overlay-root">
        <div className="overlay-header" data-tauri-drag-region="deep">
          <span className="overlay-rec-dot live" />
          <div className="overlay-title">Session Ended</div>
          <div className="overlay-header-actions">
            <button className="overlay-icon-button close" onClick={closeOverlay} title="Close">
              ✕
            </button>
          </div>
        </div>
        <div className="overlay-chat" ref={scrollRef}>
          <ConsultingNotesView notes={notes} />
        </div>
      </div>
    );
  }

  return (
    <div className="overlay-root">
      <div className="overlay-header" data-tauri-drag-region="deep">
        <span className={`overlay-rec-dot ${busy ? "busy" : "live"}`} title={busy ? "Answering…" : "Listening"} />
        <div className="overlay-title">{busy ? "Answering…" : "Consulting Session"}</div>
        <div className="overlay-header-actions">
          <button
            className="overlay-text-button"
            onClick={endSession}
            disabled={ending}
            title="End the session and see the notes"
          >
            {ending ? "Ending…" : "End Session"}
          </button>
          <button className="overlay-icon-button close" onClick={requestClose} title="Close">
            ✕
          </button>
        </div>
      </div>

      {confirmingClose ? (
        <div className="overlay-confirm-close">
          <p className="overlay-confirm-close-title">Is the session over?</p>
          <p className="overlay-confirm-close-body">Closing without ending the session will lose the notes.</p>
          <div className="overlay-confirm-close-actions">
            <button className="overlay-text-button" onClick={() => setConfirmingClose(false)}>
              Keep going
            </button>
            <button className="overlay-text-button primary" onClick={closeOverlay}>
              Close anyway
            </button>
          </div>
        </div>
      ) : (
        <>
          <div className="tracked-panel tracked-panel-5">
            {TRACKED_COLUMNS.map((col) => (
              <div className="tracked-col" key={col.kind}>
                <span className="tracked-col-label">{col.label}</span>
                <div className="tracked-chips">
                  {tracked[col.kind].map((r, i) => (
                    <span className="tracked-chip" key={i}>
                      {r}
                    </span>
                  ))}
                </div>
                {col.ownerField && (
                  <input
                    className="tracked-add-input"
                    value={quickOwner}
                    onChange={(e) => setQuickOwner(e.target.value)}
                    placeholder="Owner"
                  />
                )}
                <div className="tracked-add-row">
                  <input
                    className="tracked-add-input"
                    value={quickEntry[col.kind]}
                    onChange={(e) => setQuickEntry((p) => ({ ...p, [col.kind]: e.target.value }))}
                    onKeyDown={(e) => e.key === "Enter" && addTracked(col.kind)}
                    placeholder="+ Add"
                  />
                </div>
              </div>
            ))}
          </div>

          <div className="overlay-chat" ref={scrollRef}>
            {!hasConversation && transcript.length === 0 && (
              <p className="overlay-empty">Waiting for the session to begin…</p>
            )}

            {transcript.map((entry) => (
              <div className="chat-message interviewer" key={entry.id}>
                <span className="chat-role">{entry.speaker}</span>
                <p className="chat-text">{entry.text}</p>
              </div>
            ))}

            {turns.map((turn) => (
              <div key={turn.id} className="chat-turn">
                <div className="chat-message interviewer">
                  <span className="chat-role">You asked</span>
                  <p className="chat-text">{turn.question}</p>
                </div>
                <div className={`chat-message assistant${turn.failed ? " failed" : ""}`}>
                  <span className="chat-role">Suggestion</span>
                  {turn.answer ? (
                    <div className="chat-text chat-markdown">
                      <ReactMarkdown>{turn.answer}</ReactMarkdown>
                    </div>
                  ) : turn.failed ? (
                    <p className="chat-text muted">Couldn't get a suggestion.</p>
                  ) : (
                    <p className="chat-text muted thinking">Thinking…</p>
                  )}
                </div>
              </div>
            ))}
          </div>

          <div className="overlay-compose">
            <textarea
              ref={questionRef}
              className="overlay-question-input"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={handleQuestionKeyDown}
              placeholder="Ask for a suggestion…"
              rows={1}
            />
            <button
              className="overlay-ask-button"
              onClick={askAI}
              disabled={!question.trim() || busy}
              title="Get Suggestion (Enter)"
            >
              Get Suggestion
            </button>
          </div>

          {error && <p className="overlay-error">{error}</p>}
          {captureExcluded === false && (
            <p className="overlay-error">Warning: this window may be visible in screen shares.</p>
          )}
        </>
      )}
    </div>
  );
}
