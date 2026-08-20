import { useCallback, useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { getCurrentWebviewWindow } from "@tauri-apps/api/webviewWindow";
import ReactMarkdown from "react-markdown";
import type { TranscriptSegment } from "./types";
import { MeetingSummaryView, type MeetingSummary } from "./MeetingSummary";
import {
  loadMeetingOverlaySettings,
  saveMeetingOverlaySettings,
  SIZE_FRACTIONS,
  type MeetingOverlaySettings,
} from "./meetingOverlaySettings";
import { MeetingOverlaySettingsPanel } from "./MeetingOverlaySettingsPanel";

/// Range for the header's opacity slider — matches Interview Mode's overlay
/// (see OPACITY_MIN/MAX in InterviewOverlay.tsx and MIN_USABLE_OPACITY in
/// meetingOverlaySettings.ts).
const OPACITY_MIN = 0.15;
const OPACITY_MAX = 1;

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
  speaker: "Others" | "Me";
  text: string;
}

type TrackedKind = "KEY_POINT" | "DECISION" | "ACTION_ITEM";

interface ActiveMeetingInfo {
  meetingTitle: string;
  participants: string;
}

const overlayWindow = getCurrentWebviewWindow();

function loadActiveMeeting(): ActiveMeetingInfo {
  try {
    const raw = window.localStorage.getItem("meeting-mode:active-meeting");
    if (!raw) return { meetingTitle: "", participants: "" };
    const parsed = JSON.parse(raw);
    return {
      meetingTitle: parsed.meetingTitle || "",
      participants: parsed.participants || "",
    };
  } catch {
    return { meetingTitle: "", participants: "" };
  }
}

export function MeetingOverlay() {
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [captureExcluded, setCaptureExcluded] = useState<boolean | null>(null);
  const [confirmingClose, setConfirmingClose] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  // Shows the opacity percentage in the header for a moment after adjusting
  // — matches Interview Mode's overlay.
  const [opacityHint, setOpacityHint] = useState(false);
  const [settings, setSettings] = useState<MeetingOverlaySettings>(() => loadMeetingOverlaySettings());
  const [transcript, setTranscript] = useState<TranscriptEntry[]>([]);
  const [keyPoints, setKeyPoints] = useState<string[]>([]);
  const [decisions, setDecisions] = useState<string[]>([]);
  const [actionItems, setActionItems] = useState<string[]>([]);
  const [quickEntry, setQuickEntry] = useState<Record<TrackedKind, string>>({
    KEY_POINT: "",
    DECISION: "",
    ACTION_ITEM: "",
  });
  const [summary, setSummary] = useState<MeetingSummary | null>(null);
  const [ending, setEnding] = useState(false);

  const questionRef = useRef<HTMLTextAreaElement | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const busyRef = useRef(false);
  const sessionStartedAtRef = useRef(Date.now());
  const meetingInfoRef = useRef<ActiveMeetingInfo>(loadActiveMeeting());
  // All transcript segments (as they finalize), used to build turns for
  // end_meeting — kept separate from the trimmed `transcript` UI list.
  const rawTurnsRef = useRef<{ speaker: "ME" | "OTHER"; text: string }[]>([]);
  const hintTimerRef = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (hintTimerRef.current) window.clearTimeout(hintTimerRef.current);
    },
    [],
  );

  useEffect(() => {
    saveMeetingOverlaySettings(settings);
  }, [settings]);

  useEffect(() => {
    invoke<OverlayCaptureStatus>("show_meeting_overlay")
      .then((status) => setCaptureExcluded(status.excluded))
      .catch((e) => setError(String(e)));

    // A brand-new overlay window starts at the Rust-side default size, which
    // does not know about a returning user's saved Small/Medium/Large choice
    // — apply it here, same as Interview Mode's overlay.
    invoke("resize_meeting_overlay", { fraction: SIZE_FRACTIONS[settings.size] }).catch(() => {
      // Best-effort — the window simply stays at its default size.
    });

    invoke("start_system_audio_capture").catch((e) => {
      if (String(e) !== "capture already running") {
        setError(`Could not start audio capture: ${String(e)}`);
      }
    });
  }, []);

  useEffect(() => {
    const unlistenTranscript = listen<TranscriptSegment>("transcript:update", (event) => {
      const segment = event.payload;
      const speaker = segment.source === "SYSTEM_AUDIO" ? "Others" : "Me";
      if (segment.final_text) {
        setTranscript((prev) => [
          ...prev.slice(-49),
          { id: segment.id, speaker, text: segment.final_text as string },
        ]);
        rawTurnsRef.current.push({
          speaker: speaker === "Others" ? "OTHER" : "ME",
          text: segment.final_text,
        });
      }
    });

    const unlistenDelta = listen<string>("meeting-mode:answer-delta", (event) => {
      setTurns((prev) => {
        if (!prev.length) return prev;
        const last = prev[prev.length - 1];
        if (!last.pending) return prev;
        return [...prev.slice(0, -1), { ...last, answer: last.answer + event.payload }];
      });
    });

    const unlistenComplete = listen<string>("meeting-mode:answer-complete", (event) => {
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
      const info = meetingInfoRef.current;
      await invoke<string>("ask_meeting_question", {
        question: trimmed,
        history,
        options: {
          answerLength: "default",
          responseStyle: "natural",
          meetingTitle: info.meetingTitle || null,
          participants: info.participants || null,
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
      await invoke("track_meeting_item", { kind, text });
      if (kind === "KEY_POINT") setKeyPoints((prev) => [...prev, text]);
      if (kind === "DECISION") setDecisions((prev) => [...prev, text]);
      if (kind === "ACTION_ITEM") setActionItems((prev) => [...prev, text]);
      setQuickEntry((prev) => ({ ...prev, [kind]: "" }));
    } catch (e) {
      setError(String(e));
    }
  }, [quickEntry]);

  const closeOverlay = useCallback(async () => {
    setConfirmingClose(false);
    invoke("hide_meeting_overlay").catch(() => overlayWindow.hide());
  }, []);

  const endMeeting = useCallback(async () => {
    setEnding(true);
    setError(null);
    try {
      await invoke("stop_audio_capture").catch(() => {});
      const info = meetingInfoRef.current;
      const result = await invoke<MeetingSummary>("end_meeting", {
        turns: rawTurnsRef.current,
        meetingTitle: info.meetingTitle || null,
        participants: info.participants || null,
      });
      setSummary(result);
      try {
        await invoke("archive_meeting", {
          startedAtMs: sessionStartedAtRef.current,
          meetingTitle: info.meetingTitle || null,
          participants: info.participants || null,
          turns: rawTurnsRef.current,
          summary: result,
        });
      } catch (e) {
        console.error("Failed to archive meeting:", e);
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

  const handleOpacityChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const next = Math.min(OPACITY_MAX, Math.max(OPACITY_MIN, Number(e.target.value)));
    setSettings((prev) => ({ ...prev, opacity: next }));
    setOpacityHint(true);
    if (hintTimerRef.current) window.clearTimeout(hintTimerRef.current);
    hintTimerRef.current = window.setTimeout(() => setOpacityHint(false), 1000);
  }, []);

  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (confirmingClose) {
        if (e.key === "Escape") setConfirmingClose(false);
        return;
      }
      if (settingsOpen) {
        if (e.key === "Escape") setSettingsOpen(false);
        return;
      }
      const activeIsTextarea = document.activeElement === questionRef.current;
      if (e.key === "Enter" && !activeIsTextarea && !summary) {
        e.preventDefault();
        askAI();
      } else if (e.key === "Escape") {
        requestClose();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [askAI, settingsOpen, confirmingClose, requestClose, summary]);

  const hasConversation = turns.length > 0;
  const opacityPercent = Math.round(settings.opacity * 100);
  const overlayStyle: React.CSSProperties = {
    fontSize: `${settings.fontSize}px`,
    ["--overlay-alpha" as string]: settings.opacity,
  };

  if (summary) {
    return (
      <div
        className={`overlay-root density-${settings.density} size-${settings.size}`}
        style={overlayStyle}
      >
        <div
          className="overlay-header"
          data-tauri-drag-region={settings.dragEnabled ? "deep" : undefined}
        >
          <span className="overlay-rec-dot live" />
          <div className="overlay-title">Meeting Ended</div>
          <div className="overlay-header-actions">
            <button className="overlay-icon-button close" onClick={closeOverlay} title="Close">
              ✕
            </button>
          </div>
        </div>
        <div className="overlay-chat" ref={scrollRef}>
          <MeetingSummaryView summary={summary} />
        </div>
      </div>
    );
  }

  return (
    <div
      className={`overlay-root density-${settings.density} size-${settings.size}`}
      style={overlayStyle}
    >
      <div
        className="overlay-header"
        data-tauri-drag-region={settings.dragEnabled ? "deep" : undefined}
      >
        <span className={`overlay-rec-dot ${busy ? "busy" : "live"}`} title={busy ? "Answering…" : "Listening"} />
        <div className="overlay-title">
          {opacityHint ? `Opacity ${opacityPercent}%` : busy ? "Answering…" : "Meeting"}
        </div>
        <div className="overlay-header-actions">
          <input
            type="range"
            className="overlay-opacity-slider"
            min={OPACITY_MIN}
            max={OPACITY_MAX}
            step={0.01}
            value={settings.opacity}
            onChange={handleOpacityChange}
            aria-label="Overlay opacity"
            title={`Opacity — ${opacityPercent}%`}
          />
          <button
            className="overlay-icon-button"
            onClick={() => setSettingsOpen((v) => !v)}
            title="Settings"
          >
            ⚙
          </button>
          <button
            className="overlay-text-button"
            onClick={endMeeting}
            disabled={ending}
            title="End the meeting and see the summary"
          >
            {ending ? "Ending…" : "End Meeting"}
          </button>
          <button className="overlay-icon-button close" onClick={requestClose} title="Close">
            ✕
          </button>
        </div>
      </div>

      {confirmingClose ? (
        <div className="overlay-confirm-close">
          <p className="overlay-confirm-close-title">Is the meeting over?</p>
          <p className="overlay-confirm-close-body">Closing without ending the meeting will lose the summary.</p>
          <div className="overlay-confirm-close-actions">
            <button className="overlay-text-button" onClick={() => setConfirmingClose(false)}>
              Keep going
            </button>
            <button className="overlay-text-button primary" onClick={closeOverlay}>
              Close anyway
            </button>
          </div>
        </div>
      ) : settingsOpen ? (
        <MeetingOverlaySettingsPanel
          settings={settings}
          onChange={setSettings}
          onClose={() => setSettingsOpen(false)}
          captureExcluded={captureExcluded}
        />
      ) : (
        <>
          <div className="tracked-panel">
            <div className="tracked-col">
              <span className="tracked-col-label">Key Points</span>
              <div className="tracked-chips">
                {keyPoints.map((r, i) => (
                  <span className="tracked-chip" key={i}>
                    {r}
                  </span>
                ))}
              </div>
              <div className="tracked-add-row">
                <input
                  className="tracked-add-input"
                  value={quickEntry.KEY_POINT}
                  onChange={(e) => setQuickEntry((p) => ({ ...p, KEY_POINT: e.target.value }))}
                  onKeyDown={(e) => e.key === "Enter" && addTracked("KEY_POINT")}
                  placeholder="+ Add"
                />
              </div>
            </div>
            <div className="tracked-col">
              <span className="tracked-col-label">Decisions</span>
              <div className="tracked-chips">
                {decisions.map((r, i) => (
                  <span className="tracked-chip good" key={i}>
                    {r}
                  </span>
                ))}
              </div>
              <div className="tracked-add-row">
                <input
                  className="tracked-add-input"
                  value={quickEntry.DECISION}
                  onChange={(e) => setQuickEntry((p) => ({ ...p, DECISION: e.target.value }))}
                  onKeyDown={(e) => e.key === "Enter" && addTracked("DECISION")}
                  placeholder="+ Add"
                />
              </div>
            </div>
            <div className="tracked-col">
              <span className="tracked-col-label">Action Items</span>
              <div className="tracked-chips">
                {actionItems.map((r, i) => (
                  <span className="tracked-chip warn" key={i}>
                    {r}
                  </span>
                ))}
              </div>
              <div className="tracked-add-row">
                <input
                  className="tracked-add-input"
                  value={quickEntry.ACTION_ITEM}
                  onChange={(e) => setQuickEntry((p) => ({ ...p, ACTION_ITEM: e.target.value }))}
                  onKeyDown={(e) => e.key === "Enter" && addTracked("ACTION_ITEM")}
                  placeholder="+ Add"
                />
              </div>
            </div>
          </div>

          <div className="overlay-chat" ref={scrollRef}>
            {!hasConversation && transcript.length === 0 && (
              <p className="overlay-empty">Waiting for the meeting to begin…</p>
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
                  <span className="chat-role">Answer</span>
                  {turn.answer ? (
                    <div className="chat-text chat-markdown">
                      <ReactMarkdown>{turn.answer}</ReactMarkdown>
                    </div>
                  ) : turn.failed ? (
                    <p className="chat-text muted">Couldn't get an answer.</p>
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
              placeholder="Ask a question…"
              rows={1}
            />
            <button
              className="overlay-ask-button"
              onClick={askAI}
              disabled={!question.trim() || busy}
              title="Ask (Enter)"
            >
              Ask
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
