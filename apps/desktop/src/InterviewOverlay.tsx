import { useCallback, useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { listen } from "@tauri-apps/api/event";
import { getCurrentWebviewWindow } from "@tauri-apps/api/webviewWindow";
import ReactMarkdown from "react-markdown";
import type { TranscriptSegment } from "./types";
import {
  loadOverlaySettings,
  saveOverlaySettings,
  SIZE_FRACTIONS,
  type AnswerLength,
  type OverlaySettings,
  type ResponseStyle,
} from "./overlaySettings";
import { OverlaySettingsPanel } from "./OverlaySettingsPanel";
import {
  AUTO_AI_SILENCE_MS_COMPLETE,
  AUTO_AI_SILENCE_MS_INCOMPLETE,
  classifyQuestionCompleteness,
  joinSpeech,
} from "./questionCompleteness";

interface OverlayCaptureStatus {
  excluded: boolean;
}

/// One exchange in the running conversation.
///
/// `answer` is empty while the reply is still streaming; `pending` marks the
/// turn currently being answered so the UI can show a thinking state without a
/// separate top-level status variable.
interface Turn {
  id: string;
  question: string;
  answer: string;
  pending: boolean;
  failed?: boolean;
}

const overlayWindow = getCurrentWebviewWindow();

/// Cap on how tall the question box can grow before it scrolls internally
/// instead of continuing to shrink the conversation area above it.
const MAX_QUESTION_INPUT_PX = 160;

/// Range for the header's opacity slider. The floor matches
/// `MIN_USABLE_OPACITY` in overlaySettings.ts — below that the overlay is hard
/// to find on a busy desktop, and a user who cannot see it cannot drag the
/// slider back up.
const OPACITY_MIN = 0.15;
const OPACITY_MAX = 1;

// Auto AI silence-window constants, the completeness classifier, and
// joinSpeech() now live in questionCompleteness.ts, shared with Custom
// Agents' overlay so both Auto AI implementations behave identically.

export function InterviewOverlay() {
  // The whole conversation, oldest first. Nothing is ever removed or replaced
  // — a new question appends, and streaming deltas only ever mutate the last
  // turn's answer.
  const [turns, setTurns] = useState<Turn[]>([]);
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [captureExcluded, setCaptureExcluded] = useState<boolean | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [confirmingClose, setConfirmingClose] = useState(false);
  // Shows the opacity percentage in the header for a moment after adjusting.
  const [opacityHint, setOpacityHint] = useState(false);
  const [settings, setSettings] = useState<OverlaySettings>(() => loadOverlaySettings());

  const questionRef = useRef<HTMLTextAreaElement | null>(null);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  // Everything the interviewer has said since the last "Ask AI", as finalized
  // by STT. This is the buffer that makes the field behave like continuous
  // dictation across pauses.
  //
  // The STT layer finalizes an utterance whenever it hears trailing silence,
  // and then starts a *fresh* segment for whatever is said next. That is
  // correct behaviour for a transcript, but the overlay must not treat it as
  // "the question ended" — a speaker pausing mid-sentence would otherwise have
  // everything before the pause replaced by the few words after it. So finals
  // accumulate here and are only cleared by an explicit user action.
  const committedRef = useRef("");
  const sessionStartedAtRef = useRef(Date.now());
  // Mirrors `busy` for the event listeners, which close over stale state
  // otherwise. Answer deltas must keep landing regardless of re-renders.
  const busyRef = useRef(false);
  const hintTimerRef = useRef<number | null>(null);
  // Auto AI: debounce timer that fires askAI() once the interviewer has
  // stopped talking for AUTO_AI_SILENCE_MS. Lives in a ref (not state) since
  // it's set/cleared from the transcript listener, which must not re-subscribe
  // on every keystroke-equivalent state change.
  const autoAiTimerRef = useRef<number | null>(null);
  // askAI/settings change identity on every render; mirrored into refs so the
  // transcript listener (subscribed once, on mount) always calls the latest
  // version instead of one captured at effect-setup time.
  const askAIRef = useRef<() => void>(() => {});
  const autoAIEnabledRef = useRef(false);

  useEffect(
    () => () => {
      if (hintTimerRef.current) window.clearTimeout(hintTimerRef.current);
    },
    [],
  );

  useEffect(() => {
    saveOverlaySettings(settings);
  }, [settings]);

  useEffect(() => {
    autoAIEnabledRef.current = settings.autoAI;
    // Turning Auto AI off mid-pause must cancel any timer already counting
    // down — otherwise a question could still auto-send just after the user
    // switched it off.
    if (!settings.autoAI && autoAiTimerRef.current) {
      window.clearTimeout(autoAiTimerRef.current);
      autoAiTimerRef.current = null;
    }
  }, [settings.autoAI]);

  // Live transcript feed: reuse the exact same "transcript:update" event the
  // main window listens to (see App.tsx) — both windows share the same Rust
  // backend process/state, so no separate capture pipeline is needed here.
  //
  // This behaves like continuous dictation. There is deliberately no question
  // detection, no sentence-end detection, and nothing that clears the field on
  // silence: finalized utterances are appended to a running buffer and only an
  // explicit "Ask AI" (or the user editing/clearing it) ends the question.
  //
  // Auto AI (when enabled in settings) layers a silence-based heuristic on
  // top of this same buffer rather than replacing it: any new partial/final
  // text always resets the debounce timer below, so a mid-question pause
  // never gets treated as "done" — only a real gap in speech does, the same
  // signal a human listener would use. How long that gap needs to be is
  // itself adaptive: classifyQuestionCompleteness() judges from the buffered
  // text's own wording whether it reads as a finished question or a
  // trailing clause, so a genuine pause mid-question ("I used this
  // because...") gets more room to continue before Auto AI gives up and
  // sends it, while a question that already reads as complete fires quickly.
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
      const delay =
        completeness === "complete" ? AUTO_AI_SILENCE_MS_COMPLETE : AUTO_AI_SILENCE_MS_INCOMPLETE;
      autoAiTimerRef.current = window.setTimeout(() => {
        autoAiTimerRef.current = null;
        askAIRef.current();
      }, delay);
    };

    const unlistenTranscript = listen<TranscriptSegment>("transcript:update", (event) => {
      const segment = event.payload;
      if (segment.source !== "SYSTEM_AUDIO") return;
      // While an answer is streaming, keep buffering finals silently: the
      // interviewer may already be asking the next question. They land in the
      // field, not in the answer that's still arriving.
      if (segment.final_text) {
        committedRef.current = joinSpeech(committedRef.current, segment.final_text);
        setQuestion(committedRef.current);
        armAutoAiTimer();
      } else if (segment.partial_text) {
        setQuestion(joinSpeech(committedRef.current, segment.partial_text));
        // Still speaking — any timer counting down from an earlier final must
        // not fire mid-sentence.
        clearAutoAiTimer();
      }
    });

    // Deltas always belong to the last turn — it is the only one that can be
    // pending, because Ask AI is disabled until the previous answer completes.
    const unlistenDelta = listen<string>("interview-mode:answer-delta", (event) => {
      setTurns((prev) => {
        if (!prev.length) return prev;
        const last = prev[prev.length - 1];
        if (!last.pending) return prev;
        return [...prev.slice(0, -1), { ...last, answer: last.answer + event.payload }];
      });
    });

    const unlistenComplete = listen<string>("interview-mode:answer-complete", (event) => {
      setTurns((prev) => {
        if (!prev.length) return prev;
        const last = prev[prev.length - 1];
        if (!last.pending) return prev;
        // Prefer the completed answer from the event: it is authoritative,
        // where the accumulated deltas could have dropped one.
        return [
          ...prev.slice(0, -1),
          { ...last, answer: event.payload || last.answer, pending: false },
        ];
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
    invoke<OverlayCaptureStatus>("show_interview_overlay")
      .then((status) => setCaptureExcluded(status.excluded))
      .catch((e) => setError(String(e)));

    // A brand-new overlay window is created at the Rust-side default size
    // (interview_mode::window::DEFAULT_SIZE_FRACTION), which does not know
    // about a returning user's saved Small/Medium/Large choice. Apply it here
    // so that choice takes effect immediately rather than only after the user
    // next opens Settings and touches the size control themselves.
    invoke("resize_interview_overlay", { fraction: SIZE_FRACTIONS[settings.size] }).catch(() => {
      // Best-effort — the window simply stays at its default size.
    });

    // Interview Mode can now be opened without having started a recording
    // first (see App.tsx), but the live transcript this overlay listens to
    // only exists once WASAPI+STT capture is actually running. Start it here
    // if it isn't already active so "Listening" is never just a silent
    // no-op; "capture already running" from a prior Start Recording click is
    // the one expected/harmless failure — anything else (e.g. no audio
    // device) must surface, or the overlay would sit on "Waiting for the
    // interviewer to speak…" forever with no explanation.
    invoke("start_system_audio_capture").catch((e) => {
      if (String(e) !== "capture already running") {
        setError(`Could not start audio capture: ${String(e)}`);
      }
    });
  }, []);

  // Follow the conversation as it grows, the way a chat window does.
  useEffect(() => {
    const el = scrollRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [turns, question]);

  const askAI = useCallback(async () => {
    const trimmed = question.trim();
    if (!trimmed || busyRef.current) return;

    setError(null);
    // The question moves into the conversation and the buffer resets, so
    // anything said from here starts the next question instead of being
    // appended onto one already sent.
    const turn: Turn = {
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      question: trimmed,
      answer: "",
      pending: true,
    };
    setTurns((prev) => [...prev, turn]);
    setQuestion("");
    committedRef.current = "";
    busyRef.current = true;
    setBusy(true);

    // Prior turns only — the one just pushed is the current question, and
    // completed turns are the only ones worth replaying.
    const history = turns
      .filter((t) => !t.pending && t.answer.trim() && !t.failed)
      .map((t) => ({ question: t.question, answer: t.answer }));

    try {
      await invoke<string>("ask_interview_question", {
        question: trimmed,
        history,
        options: {
          answerLength: settings.answerLength,
          responseStyle: settings.responseStyle,
          role: settings.role.trim() || null,
          jobDescription: settings.jobDescription.trim() || null,
          englishLevel: settings.englishLevel,
          humanization: settings.humanization,
        },
      });
    } catch (e) {
      setError(String(e));
      // Keep the question visible in the conversation and mark it failed,
      // rather than silently dropping what the interviewer asked.
      setTurns((prev) =>
        prev.map((t) => (t.id === turn.id ? { ...t, pending: false, failed: true } : t)),
      );
      busyRef.current = false;
      setBusy(false);
    }
  }, [question, turns, settings]);

  useEffect(() => {
    askAIRef.current = askAI;
  }, [askAI]);

  // Archives the Q&A turns so far as one history entry, then hides the
  // overlay. Turns still pending/failed are skipped — only completed
  // exchanges are worth keeping. An empty result (nothing ever asked) is a
  // no-op on the Rust side, so opening and closing without using it never
  // clutters history.
  //
  // The overlay window itself is never destroyed between interviews — Rust's
  // show_overlay_window reuses the existing webview (see interview_mode/
  // window.rs) purely for speed, so this component never remounts and its
  // React state would otherwise survive from one interview into the next.
  // Clearing turns/question/committedRef/sessionStartedAtRef here, right
  // after archiving, is what makes the *next* "Start Interview" actually
  // start blank instead of resuming the just-archived conversation.
  const closeOverlay = useCallback(async () => {
    setConfirmingClose(false);
    const completed = turns
      .filter((t) => !t.pending && !t.failed && t.answer.trim())
      .map((t) => ({ question: t.question, answer: t.answer }));
    try {
      await invoke("archive_interview_session", {
        startedAtMs: sessionStartedAtRef.current,
        role: settings.role.trim() || null,
        company: settings.company.trim() || null,
        turns: completed,
      });
    } catch (e) {
      console.error("Failed to archive interview session:", e);
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

    invoke("hide_interview_overlay").catch(() => overlayWindow.hide());
  }, [turns, settings.role, settings.company]);

  // Entry point for both the ✕ button and Escape: conversations with at least
  // one exchange ask for confirmation first (closing mid-interview is easy to
  // trigger by accident), while an empty session just closes immediately —
  // there's nothing to lose by skipping the prompt.
  const requestClose = useCallback(() => {
    const hasConversation = turns.some((t) => !t.pending && t.answer.trim());
    if (hasConversation) {
      setConfirmingClose(true);
    } else {
      closeOverlay();
    }
  }, [turns, closeOverlay]);

  // Grows the textarea to fit its content, up to MAX_QUESTION_INPUT_PX — past
  // that it scrolls internally instead of continuing to eat the conversation
  // area above it. Plain CSS can't do this (a textarea's height doesn't track
  // its own content), so height is measured and set imperatively whenever the
  // text changes, including from STT — a long dictated question needs this
  // exactly as much as one the user typed.
  const autoGrow = useCallback(() => {
    const el = questionRef.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, MAX_QUESTION_INPUT_PX)}px`;
  }, []);

  const handleQuestionChange = useCallback(
    (e: React.ChangeEvent<HTMLTextAreaElement>) => {
      // Adopt the user's text as the new buffer. Without this, a later
      // utterance would append onto the pre-edit text and silently undo their
      // correction.
      committedRef.current = e.target.value;
      setQuestion(e.target.value);
    },
    [],
  );

  // Runs after every render where `question` changed — covers typing, STT
  // partials/finals, and the reset to "" after Ask AI — rather than being
  // wired into each of those call sites individually.
  useEffect(() => {
    autoGrow();
  }, [question, autoGrow]);

  const handleQuestionKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        askAI();
      }
      // Shift+Enter falls through to the textarea's default behavior and
      // inserts a newline.
    },
    [askAI],
  );

  const handleOpacityChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const next = Math.min(OPACITY_MAX, Math.max(OPACITY_MIN, Number(e.target.value)));
    setSettings((prev) => ({ ...prev, opacity: next }));
    // Show the percentage while dragging, then get out of the way.
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
      // The textarea has its own Enter/Shift+Enter handling above; this
      // top-level listener only needs to cover ESC (hide) globally and ENTER
      // when focus is somewhere else in the overlay.
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

  const overlayStyle: React.CSSProperties = {
    fontSize: `${settings.fontSize}px`,
    // Applied to the panel background rather than the whole element, so text
    // stays fully legible while the window itself reads as translucent.
    ["--overlay-alpha" as string]: settings.opacity,
  };

  const hasConversation = turns.length > 0;
  const opacityPercent = Math.round(settings.opacity * 100);

  return (
    <div
      className={`overlay-root density-${settings.density} size-${settings.size}`}
      style={overlayStyle}
    >
      {/* "deep" so the whole bar drags — including the empty space and the
          status dot — rather than only direct clicks on this exact element,
          which is what a bare attribute means. Safe for the controls on the
          right: Tauri's drag script treats BUTTON/INPUT as clickable and
          blocks dragging for them (tauri/src/window/scripts/drag.js). */}
      <div
        className="overlay-header"
        data-tauri-drag-region={settings.dragEnabled ? "deep" : undefined}
      >
        <span
          className={`overlay-rec-dot ${busy ? "busy" : "live"}`}
          title={busy ? "Answering…" : "Listening"}
        />
        <div className="overlay-title">
          {/* While adjusting, the title doubles as the readout — the change
              itself can be hard to judge against a dark desktop, and this
              avoids spending permanent header space on a number. */}
          {opacityHint ? `Opacity ${opacityPercent}%` : busy ? "Answering…" : "Listening"}
        </div>

        <div className="overlay-header-actions">
          {/* A <button>, not a checkbox+<label>: Tauri's drag script already
              treats BUTTON as clickable and blocks dragging for it (see the
              comment on the opacity slider below), and a bare button avoids
              the <label> pitfall that comment warns about — no risk of the
              click handing the drag gesture back to the window. */}
          <button
            type="button"
            className={`overlay-auto-ai-toggle${settings.autoAI ? " on" : ""}`}
            onClick={() => setSettings((prev) => ({ ...prev, autoAI: !prev.autoAI }))}
            title={
              settings.autoAI
                ? "Auto AI is on — questions send automatically when the interviewer stops talking"
                : "Auto AI is off — use Ask AI or Enter to send"
            }
          >
            <span className="overlay-auto-ai-dot" />
            Auto AI
          </button>

          {/* Safe inside the header's drag region without any extra handling:
              Tauri's drag script treats INPUT as clickable and blocks dragging
              for it (see tauri/src/window/scripts/drag.js). Do NOT wrap this in
              a <label> or give it a data-tauri-drag-region attribute — either
              would hand the gesture back to the window and make the bar
              undraggable. */}
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
          <button className="overlay-icon-button close" onClick={requestClose} title="Close (Esc)">
            ✕
          </button>
        </div>
      </div>

      {confirmingClose ? (
        <div className="overlay-confirm-close">
          <p className="overlay-confirm-close-title">Is the interview over?</p>
          <p className="overlay-confirm-close-body">
            Closing will save this conversation to your interview history.
          </p>
          <div className="overlay-confirm-close-actions">
            <button className="overlay-text-button" onClick={() => setConfirmingClose(false)}>
              Keep going
            </button>
            <button className="overlay-text-button primary" onClick={closeOverlay}>
              Yes, end interview
            </button>
          </div>
        </div>
      ) : settingsOpen ? (
        <OverlaySettingsPanel
          settings={settings}
          onChange={setSettings}
          onClose={() => setSettingsOpen(false)}
          captureExcluded={captureExcluded}
        />
      ) : (
        <>
          <div className="overlay-chat" ref={scrollRef}>
            {!hasConversation && !question && (
              <p className="overlay-empty">Waiting for the interviewer to speak…</p>
            )}

            {turns.map((turn) => (
              <div key={turn.id} className="chat-turn">
                <div className="chat-message interviewer">
                  <span className="chat-role">Interviewer</span>
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
              onChange={handleQuestionChange}
              onKeyDown={handleQuestionKeyDown}
              placeholder={hasConversation ? "Next question…" : "Waiting for the interviewer to speak…"}
              rows={1}
            />
            <button
              className="overlay-ask-button"
              onClick={askAI}
              disabled={!question.trim() || busy}
              title="Ask AI (Enter)"
            >
              Ask AI
            </button>
          </div>

          {error && <p className="overlay-error">{error}</p>}
        </>
      )}
    </div>
  );
}

export type { AnswerLength, ResponseStyle };
