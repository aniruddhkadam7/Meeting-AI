import { useCallback, useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { getCurrentWebviewWindow } from "@tauri-apps/api/webviewWindow";
import ReactMarkdown from "react-markdown";
import type { TranscriptSegment } from "./types";
import { SalesSummaryView, type SalesCallSummary } from "./SalesSummary";

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
  speaker: "Customer" | "Rep";
  text: string;
}

type TrackedKind = "REQUIREMENT" | "OBJECTION" | "COMMITMENT";

interface ActiveCallInfo {
  customerName: string;
  companyName: string;
  callStage: string;
}

const overlayWindow = getCurrentWebviewWindow();

function loadActiveCall(): ActiveCallInfo {
  try {
    const raw = window.localStorage.getItem("sales-mode:active-call");
    if (!raw) return { customerName: "", companyName: "", callStage: "discovery" };
    const parsed = JSON.parse(raw);
    return {
      customerName: parsed.customerName || "",
      companyName: parsed.companyName || "",
      callStage: parsed.callStage || "discovery",
    };
  } catch {
    return { customerName: "", companyName: "", callStage: "discovery" };
  }
}

export function SalesOverlay() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [captureExcluded, setCaptureExcluded] = useState<boolean | null>(null);
  const [confirmingClose, setConfirmingClose] = useState(false);
  const [transcript, setTranscript] = useState<TranscriptEntry[]>([]);
  const [requirements, setRequirements] = useState<string[]>([]);
  const [objections, setObjections] = useState<string[]>([]);
  const [commitments, setCommitments] = useState<string[]>([]);
  const [quickEntry, setQuickEntry] = useState<Record<TrackedKind, string>>({
    REQUIREMENT: "",
    OBJECTION: "",
    COMMITMENT: "",
  });
  const [summary, setSummary] = useState<SalesCallSummary | null>(null);
  const [ending, setEnding] = useState(false);

  const questionRef = useRef<HTMLTextAreaElement | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const busyRef = useRef(false);
  const sessionStartedAtRef = useRef(Date.now());
  const callInfoRef = useRef<ActiveCallInfo>(loadActiveCall());
  // All transcript segments (as they finalize), used to build turns for
  // end_sales_call — kept separate from the trimmed `transcript` UI list.
  const rawTurnsRef = useRef<{ speaker: "REP" | "CUSTOMER"; text: string }[]>([]);

  useEffect(() => {
    invoke<OverlayCaptureStatus>("show_sales_overlay")
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
      const speaker = segment.source === "SYSTEM_AUDIO" ? "Customer" : "Rep";
      if (segment.final_text) {
        setTranscript((prev) => [
          ...prev.slice(-49),
          { id: segment.id, speaker, text: segment.final_text as string },
        ]);
        rawTurnsRef.current.push({
          speaker: speaker === "Customer" ? "CUSTOMER" : "REP",
          text: segment.final_text,
        });
      }
    });

    const unlistenDelta = listen<string>("sales-mode:answer-delta", (event) => {
      setTurns((prev) => {
        if (!prev.length) return prev;
        const last = prev[prev.length - 1];
        if (!last.pending) return prev;
        return [...prev.slice(0, -1), { ...last, answer: last.answer + event.payload }];
      });
    });

    const unlistenComplete = listen<string>("sales-mode:answer-complete", (event) => {
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
      const info = callInfoRef.current;
      await invoke<string>("ask_sales_question", {
        question: trimmed,
        history,
        options: {
          answerLength: "default",
          responseStyle: "natural",
          customerName: info.customerName || null,
          companyName: info.companyName || null,
          callStage: info.callStage || null,
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

  const addTracked = useCallback(async (kind: TrackedKind) => {
    const text = quickEntry[kind].trim();
    if (!text) return;
    try {
      await invoke("track_sales_item", { kind, text });
      if (kind === "REQUIREMENT") setRequirements((prev) => [...prev, text]);
      if (kind === "OBJECTION") setObjections((prev) => [...prev, text]);
      if (kind === "COMMITMENT") setCommitments((prev) => [...prev, text]);
      setQuickEntry((prev) => ({ ...prev, [kind]: "" }));
    } catch (e) {
      setError(String(e));
    }
  }, [quickEntry]);

  const closeOverlay = useCallback(async () => {
    setConfirmingClose(false);
    invoke("hide_sales_overlay").catch(() => overlayWindow.hide());
  }, []);

  const endCall = useCallback(async () => {
    setEnding(true);
    setError(null);
    try {
      await invoke("stop_audio_capture").catch(() => {});
      const info = callInfoRef.current;
      const result = await invoke<SalesCallSummary>("end_sales_call", {
        turns: rawTurnsRef.current,
        customerName: info.customerName || null,
        companyName: info.companyName || null,
      });
      setSummary(result);
      try {
        await invoke("archive_sales_call", {
          startedAtMs: sessionStartedAtRef.current,
          customerName: info.customerName || null,
          companyName: info.companyName || null,
          turns: rawTurnsRef.current,
          summary: result,
        });
      } catch (e) {
        console.error("Failed to archive sales call:", e);
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setEnding(false);
    }
  }, []);

  const requestClose = useCallback(() => {
    const hasConversation = turns.length > 0 || rawTurnsRef.current.length > 0;
    if (hasConversation && !summary) {
      setConfirmingClose(true);
    } else {
      closeOverlay();
    }
  }, [turns, summary, closeOverlay]);

  const hasConversation = turns.length > 0;

  if (summary) {
    return (
      <div className="overlay-root">
        <div className="overlay-header" data-tauri-drag-region="deep">
          <span className="overlay-rec-dot live" />
          <div className="overlay-title">Call Ended</div>
          <div className="overlay-header-actions">
            <button className="overlay-icon-button close" onClick={closeOverlay} title="Close">
              ✕
            </button>
          </div>
        </div>
        <div className="overlay-chat" ref={scrollRef}>
          <SalesSummaryView summary={summary} />
        </div>
      </div>
    );
  }

  return (
    <div className="overlay-root">
      <div className="overlay-header" data-tauri-drag-region="deep">
        <span className={`overlay-rec-dot ${busy ? "busy" : "live"}`} title={busy ? "Answering…" : "Listening"} />
        <div className="overlay-title">{busy ? "Answering…" : "Sales Call"}</div>
        <div className="overlay-header-actions">
          <button
            className="overlay-text-button"
            onClick={endCall}
            disabled={ending}
            title="End the call and see the summary"
          >
            {ending ? "Ending…" : "End Call"}
          </button>
          <button className="overlay-icon-button close" onClick={requestClose} title="Close">
            ✕
          </button>
        </div>
      </div>

      {confirmingClose ? (
        <div className="overlay-confirm-close">
          <p className="overlay-confirm-close-title">Is the call over?</p>
          <p className="overlay-confirm-close-body">Closing without ending the call will lose the summary.</p>
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
          <div className="tracked-panel">
            <div className="tracked-col">
              <span className="tracked-col-label">Requirements</span>
              <div className="tracked-chips">
                {requirements.map((r, i) => (
                  <span className="tracked-chip" key={i}>
                    {r}
                  </span>
                ))}
              </div>
              <div className="tracked-add-row">
                <input
                  className="tracked-add-input"
                  value={quickEntry.REQUIREMENT}
                  onChange={(e) => setQuickEntry((p) => ({ ...p, REQUIREMENT: e.target.value }))}
                  onKeyDown={(e) => e.key === "Enter" && addTracked("REQUIREMENT")}
                  placeholder="+ Add"
                />
              </div>
            </div>
            <div className="tracked-col">
              <span className="tracked-col-label">Objections</span>
              <div className="tracked-chips">
                {objections.map((r, i) => (
                  <span className="tracked-chip warn" key={i}>
                    {r}
                  </span>
                ))}
              </div>
              <div className="tracked-add-row">
                <input
                  className="tracked-add-input"
                  value={quickEntry.OBJECTION}
                  onChange={(e) => setQuickEntry((p) => ({ ...p, OBJECTION: e.target.value }))}
                  onKeyDown={(e) => e.key === "Enter" && addTracked("OBJECTION")}
                  placeholder="+ Add"
                />
              </div>
            </div>
            <div className="tracked-col">
              <span className="tracked-col-label">Commitments</span>
              <div className="tracked-chips">
                {commitments.map((r, i) => (
                  <span className="tracked-chip good" key={i}>
                    {r}
                  </span>
                ))}
              </div>
              <div className="tracked-add-row">
                <input
                  className="tracked-add-input"
                  value={quickEntry.COMMITMENT}
                  onChange={(e) => setQuickEntry((p) => ({ ...p, COMMITMENT: e.target.value }))}
                  onKeyDown={(e) => e.key === "Enter" && addTracked("COMMITMENT")}
                  placeholder="+ Add"
                />
              </div>
            </div>
          </div>

          <div className="overlay-chat" ref={scrollRef}>
            {!hasConversation && transcript.length === 0 && (
              <p className="overlay-empty">Waiting for the call to begin…</p>
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
