import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { getCurrentWebviewWindow } from "@tauri-apps/api/webviewWindow";
import ReactMarkdown from "react-markdown";
import type { AgentPersonalization, TranscriptSegment } from "./types";
import {
  AgentOverlaySettings,
  loadAgentOverlaySettings,
  saveAgentOverlaySettings,
} from "./agentOverlaySettings";
import { AgentOverlaySettingsPanel } from "./AgentOverlaySettingsPanel";
import {
  AUTO_AI_SILENCE_MS_COMPLETE,
  AUTO_AI_SILENCE_MS_INCOMPLETE,
  classifyQuestionCompleteness,
  joinSpeech,
} from "./questionCompleteness";

interface OverlayCaptureStatus {
  excluded: boolean;
}

/// Cap on how tall the question box can grow before it scrolls internally —
/// matches InterviewOverlay.tsx's MAX_QUESTION_INPUT_PX exactly.
const MAX_QUESTION_INPUT_PX = 160;

/// Range for the header's opacity slider — matches InterviewOverlay.tsx.
const OPACITY_MIN = 0.15;
const OPACITY_MAX = 1;

interface Turn {
  id: string;
  question: string;
  answer: string;
  pending: boolean;
  failed?: boolean;
}

interface ActiveAgentInfo {
  id: string;
  name: string;
  baseRole: string | null;
  description: string | null;
  personalization: AgentPersonalization;
}

const overlayWindow = getCurrentWebviewWindow();

/// Extracts the agent id from this overlay window's label
/// (`agent-overlay-<id>`, set by agents::overlay::show_agent_overlay in
/// Rust) — this is how one generic overlay component serves every agent
/// without a separate window/component per agent.
function agentIdFromWindowLabel(): string {
  const label = overlayWindow.label;
  const prefix = "agent-overlay-";
  return label.startsWith(prefix) ? label.slice(prefix.length) : "";
}

function loadActiveAgent(agentId: string): ActiveAgentInfo | null {
  try {
    const raw = window.localStorage.getItem(`agent:${agentId}:active`);
    if (!raw) return null;
    return JSON.parse(raw) as ActiveAgentInfo;
  } catch {
    return null;
  }
}

/// The one live overlay every Custom Agent uses — predefined-role or fully
/// custom. Mirrors InterviewOverlay.tsx's shape (transparent floating window,
/// live STT-driven buffered question, streamed answer, Auto AI, per-agent
/// customizable position/size/answer display) but calls the single generic
/// ask_agent_question command instead of a mode-specific one, and has no
/// tracked-item panel (Custom Agents don't have Sales/Consulting's
/// requirement/objection/risk tracking — explicit non-goal).
export function AgentOverlay() {
  const agentId = useMemo(agentIdFromWindowLabel, []);
  const agentInfo = useMemo(() => loadActiveAgent(agentId), [agentId]);

  const [settings, setSettingsState] = useState<AgentOverlaySettings>(() => loadAgentOverlaySettings(agentId));
  const [settingsOpen, setSettingsOpen] = useState(false);

  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [captureExcluded, setCaptureExcluded] = useState<boolean | null>(null);
  const [confirmingClose, setConfirmingClose] = useState(false);
  // Shows the opacity percentage in the header for a moment after adjusting —
  // matches InterviewOverlay.tsx's opacity slider behavior exactly.
  const [opacityHint, setOpacityHint] = useState(false);

  const questionRef = useRef<HTMLTextAreaElement | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const busyRef = useRef(false);
  const sessionStartedAtRef = useRef(Date.now());
  const committedRef = useRef("");
  const autoAiTimerRef = useRef<number | null>(null);
  const autoAIEnabledRef = useRef(settings.autoAI);
  const askAIRef = useRef<() => void>(() => {});
  const hintTimerRef = useRef<number | null>(null);

  useEffect(
    () => () => {
      if (hintTimerRef.current) window.clearTimeout(hintTimerRef.current);
    },
    [],
  );

  useEffect(() => {
    autoAIEnabledRef.current = settings.autoAI;
    if (!settings.autoAI && autoAiTimerRef.current) {
      window.clearTimeout(autoAiTimerRef.current);
      autoAiTimerRef.current = null;
    }
  }, [settings.autoAI]);

  const setSettings = useCallback(
    (updater: AgentOverlaySettings | ((prev: AgentOverlaySettings) => AgentOverlaySettings)) => {
      setSettingsState((prev) => {
        const next = typeof updater === "function" ? (updater as (p: AgentOverlaySettings) => AgentOverlaySettings)(prev) : updater;
        saveAgentOverlaySettings(agentId, next);
        return next;
      });
    },
    [agentId],
  );

  useEffect(() => {
    if (!agentId) return;
    invoke<OverlayCaptureStatus>("show_agent_overlay", { agentId, agentName: agentInfo?.name ?? "Agent" })
      .then((status) => setCaptureExcluded(status.excluded))
      .catch((e) => setError(String(e)));

    invoke("start_system_audio_capture").catch((e) => {
      if (String(e) !== "capture already running") {
        setError(`Could not start audio capture: ${String(e)}`);
      }
    });
  }, [agentId, agentInfo?.name]);

  const askAI = useCallback(async () => {
    const trimmed = committedRef.current.trim() || question.trim();
    if (!trimmed || busyRef.current || !agentId) return;

    setError(null);
    const turn: Turn = {
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      question: trimmed,
      answer: "",
      pending: true,
    };
    setTurns((prev) => [...prev, turn]);
    committedRef.current = "";
    setQuestion("");
    busyRef.current = true;
    setBusy(true);

    const history = turns
      .filter((t) => !t.pending && t.answer.trim() && !t.failed)
      .map((t) => ({ question: t.question, answer: t.answer }));

    try {
      await invoke<string>("ask_agent_question", { agentId, question: trimmed, history });
    } catch (e) {
      setError(String(e));
      setTurns((prev) => prev.map((t) => (t.id === turn.id ? { ...t, pending: false, failed: true } : t)));
      busyRef.current = false;
      setBusy(false);
    }
  }, [question, turns, agentId]);

  useEffect(() => {
    askAIRef.current = askAI;
  }, [askAI]);

  // Live transcript feed — same buffered-question + Auto AI silence-debounce
  // approach as Interview Mode (see questionCompleteness.ts), scoped to this
  // agent's overlay. Manual Ask (Enter/button) always still works regardless
  // of the Auto AI setting.
  useEffect(() => {
    const clearAutoAiTimer = () => {
      if (autoAiTimerRef.current) {
        window.clearTimeout(autoAiTimerRef.current);
        autoAiTimerRef.current = null;
      }
    };

    const armAutoAiTimer = () => {
      clearAutoAiTimer();
      if (!autoAIEnabledRef.current || busyRef.current) return;
      const completeness = classifyQuestionCompleteness(committedRef.current);
      const delay = completeness === "complete" ? AUTO_AI_SILENCE_MS_COMPLETE : AUTO_AI_SILENCE_MS_INCOMPLETE;
      autoAiTimerRef.current = window.setTimeout(() => {
        autoAiTimerRef.current = null;
        askAIRef.current();
      }, delay);
    };

    const unlistenTranscript = listen<TranscriptSegment>("transcript:update", (event) => {
      const segment = event.payload;
      if (segment.final_text) {
        committedRef.current = joinSpeech(committedRef.current, segment.final_text);
        setQuestion(committedRef.current);
        armAutoAiTimer();
      } else if (segment.partial_text) {
        setQuestion(joinSpeech(committedRef.current, segment.partial_text));
        clearAutoAiTimer();
      }
    });

    const unlistenDelta = listen<string>("agent:answer-delta", (event) => {
      setTurns((prev) => {
        if (!prev.length) return prev;
        const last = prev[prev.length - 1];
        if (!last.pending) return prev;
        return [...prev.slice(0, -1), { ...last, answer: last.answer + event.payload }];
      });
    });

    const unlistenComplete = listen<string>("agent:answer-complete", (event) => {
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
      clearAutoAiTimer();
    };
  }, []);

  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [turns, question]);

  // Grows the textarea to fit its content, up to MAX_QUESTION_INPUT_PX —
  // matches InterviewOverlay.tsx's autoGrow exactly.
  const autoGrow = useCallback(() => {
    const el = questionRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_QUESTION_INPUT_PX)}px`;
  }, []);

  const handleQuestionChange = useCallback((value: string) => {
    committedRef.current = value;
    setQuestion(value);
  }, []);

  useEffect(() => {
    autoGrow();
  }, [question, autoGrow]);

  const handleQuestionKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        askAI();
      }
    },
    [askAI],
  );

  // Archives the Q&A turns so far as one history entry, then hides the
  // overlay — matches InterviewOverlay.tsx's closeOverlay exactly: a single
  // close path (✕ / Escape) rather than a separate "End" button, since
  // ending and closing are the same action here.
  const closeOverlay = useCallback(async () => {
    setConfirmingClose(false);
    const completedTurns = turns.filter((t) => !t.pending && !t.failed && t.answer.trim());
    if (completedTurns.length > 0) {
      try {
        await invoke("archive_agent_conversation", {
          agentId,
          startedAtMs: sessionStartedAtRef.current,
          turns: completedTurns.map((t) => ({ question: t.question, answer: t.answer })),
        });
      } catch (e) {
        console.error("Failed to archive agent conversation:", e);
      }
    }

    if (autoAiTimerRef.current) {
      window.clearTimeout(autoAiTimerRef.current);
      autoAiTimerRef.current = null;
    }
    committedRef.current = "";
    sessionStartedAtRef.current = Date.now();
    setTurns([]);
    setQuestion("");
    setError(null);
    busyRef.current = false;
    setBusy(false);

    invoke("hide_agent_overlay", { agentId }).catch(() => overlayWindow.hide());
  }, [turns, agentId]);

  // Entry point for both the ✕ button and Escape — matches
  // InterviewOverlay.tsx: a conversation with at least one completed
  // exchange asks for confirmation first; an empty session just closes.
  const requestClose = useCallback(() => {
    const hasConversation = turns.some((t) => !t.pending && t.answer.trim());
    if (hasConversation) {
      setConfirmingClose(true);
    } else {
      closeOverlay();
    }
  }, [turns, closeOverlay]);

  const handleOpacityChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const next = Math.min(OPACITY_MAX, Math.max(OPACITY_MIN, Number(e.target.value)));
    setSettings((prev) => ({ ...prev, opacity: next }));
    setOpacityHint(true);
    if (hintTimerRef.current) window.clearTimeout(hintTimerRef.current);
    hintTimerRef.current = window.setTimeout(() => setOpacityHint(false), 1000);
  }, [setSettings]);

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
      if (e.key === "Enter" && !activeIsTextarea) {
        e.preventDefault();
        askAI();
      } else if (e.key === "Escape") {
        requestClose();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [askAI, settingsOpen, confirmingClose, requestClose]);

  const hasConversation = turns.length > 0;
  const title = agentInfo?.name ?? "Agent";
  const displayedTurns = settings.answerDisplay === "compact" && turns.length > 0 ? [turns[turns.length - 1]] : turns;
  const opacityPercent = Math.round(settings.opacity * 100);

  const overlayStyle: React.CSSProperties = {
    fontSize: `${settings.fontSize}px`,
    ["--overlay-alpha" as string]: settings.opacity,
  };

  return (
    <div className={`overlay-root density-${settings.density} size-${settings.size}`} style={overlayStyle}>
      {/* "deep" so the whole bar drags, matching InterviewOverlay.tsx. */}
      <div
        className="overlay-header"
        data-tauri-drag-region={settings.dragEnabled ? "deep" : undefined}
      >
        <span className={`overlay-rec-dot ${busy ? "busy" : "live"}`} title={busy ? "Answering…" : "Listening"} />
        <div className="overlay-title">
          {opacityHint ? `Opacity ${opacityPercent}%` : busy ? "Answering…" : title}
        </div>

        <div className="overlay-header-actions">
          <button
            type="button"
            className={`overlay-auto-ai-toggle${settings.autoAI ? " on" : ""}`}
            onClick={() => setSettings((prev) => ({ ...prev, autoAI: !prev.autoAI }))}
            title={
              settings.autoAI
                ? "Auto AI is on — questions send automatically when you stop talking"
                : "Auto AI is off — use Ask or Enter to send"
            }
          >
            <span className="overlay-auto-ai-dot" />
            Auto AI
          </button>

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

          <button className="overlay-icon-button" onClick={() => setSettingsOpen((v) => !v)} title="Settings">
            ⚙
          </button>
          <button className="overlay-icon-button close" onClick={requestClose} title="Close (Esc)">
            ✕
          </button>
        </div>
      </div>

      {confirmingClose ? (
        <div className="overlay-confirm-close">
          <p className="overlay-confirm-close-title">Is the conversation over?</p>
          <p className="overlay-confirm-close-body">
            Closing will save this conversation to {title}'s History.
          </p>
          <div className="overlay-confirm-close-actions">
            <button className="overlay-text-button" onClick={() => setConfirmingClose(false)}>
              Keep going
            </button>
            <button className="overlay-text-button primary" onClick={closeOverlay}>
              Yes, end conversation
            </button>
          </div>
        </div>
      ) : settingsOpen ? (
        <AgentOverlaySettingsPanel
          agentId={agentId}
          settings={settings}
          onChange={setSettings}
          onClose={() => setSettingsOpen(false)}
        />
      ) : (
        <>
          <div className="overlay-chat" ref={scrollRef}>
            {!hasConversation && !question && <p className="overlay-empty">Waiting for you to speak…</p>}

            {displayedTurns.map((turn) => (
              <div key={turn.id} className="chat-turn">
                <div className="chat-message interviewer">
                  <span className="chat-role">You asked</span>
                  <p className="chat-text">{turn.question}</p>
                </div>
                <div className={`chat-message assistant${turn.failed ? " failed" : ""}`}>
                  <span className="chat-role">{title}</span>
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
              onChange={(e) => handleQuestionChange(e.target.value)}
              onKeyDown={handleQuestionKeyDown}
              placeholder={hasConversation ? "Next question…" : "Waiting for you to speak…"}
              rows={1}
            />
            <button className="overlay-ask-button" onClick={askAI} disabled={!question.trim() || busy} title="Ask AI (Enter)">
              Ask AI
            </button>
          </div>

          {error && <p className="overlay-error">{error}</p>}
          {captureExcluded === false && <p className="overlay-error">Warning: this window may be visible in screen shares.</p>}
        </>
      )}
    </div>
  );
}
