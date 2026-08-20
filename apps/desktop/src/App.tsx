import { useCallback, useEffect, useRef, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { getCurrentWindow } from "@tauri-apps/api/window";
import { listen } from "@tauri-apps/api/event";
import "./App.css";
import smallbirdLogo from "./assets/smallbird-logo.png";
import {
  DocumentContext,
  emptyDocumentContextState,
  uploadDocumentContext,
  type DocumentContextState,
} from "./DocumentContext";
import { Account } from "./Account";
import { SettingsPopover } from "./SettingsPopover";
import { UpdateBanner } from "./UpdateBanner";
import { LowEndHardwareBanner } from "./LowEndHardwareBanner";
import { InterviewHistory } from "./InterviewHistory";
import { MeetingHistory } from "./MeetingHistory";
import { HeaderDropdown } from "./HeaderDropdown";
import { answerStyleToOverlayFields, loadOverlaySettings, saveOverlaySettings } from "./overlaySettings";
import { Button } from "./ui";
import { IconAccount, IconAttachment, IconChevronDown, IconSettings } from "./Icons";
import { INTERVIEW_CONTEXT_SECTIONS, MEETING_CONTEXT_SECTIONS } from "./headerPopups";

type Mode = "INTERVIEW" | "MEETING";
type SessionState = "IDLE" | "STARTING" | "LISTENING";
type Popover = "MODE" | "CONTEXT" | "SETTINGS" | "ACCOUNT" | null;

const MODE_LABELS: Record<Mode, string> = {
  INTERVIEW: "Interview",
  MEETING: "Meeting",
};

function App() {
  const [mode, setMode] = useState<Mode>("INTERVIEW");
  const [sessionState, setSessionState] = useState<SessionState>("IDLE");
  const [openPopover, setOpenPopover] = useState<Popover>(null);
  const [error, setError] = useState<string | null>(null);
  const [isMaximized, setIsMaximized] = useState(false);
  const [historyRefreshKey] = useState(0);

  const [interviewContext, setInterviewContext] = useState<DocumentContextState>(() =>
    emptyDocumentContextState(INTERVIEW_CONTEXT_SECTIONS),
  );
  const [meetingContext, setMeetingContext] = useState<DocumentContextState>(() =>
    emptyDocumentContextState(MEETING_CONTEXT_SECTIONS),
  );
  const [meetingTitle, setMeetingTitle] = useState("");
  const [meetingParticipants, setMeetingParticipants] = useState("");

  // Prewarm STT the moment the app launches, mirroring InterviewSetup's
  // mount-time prewarm — the mic model loads while the user is still picking
  // a mode/attaching context, so Start doesn't eat the full load time.
  const prewarmRef = useRef<Promise<void> | null>(null);
  useEffect(() => {
    const promise = invoke<void>("start_system_audio_capture").catch((e) => {
      if (String(e) !== "capture already running") throw e;
    });
    prewarmRef.current = promise;
    promise.catch(() => {});
  }, []);

  // History/status content only has room to render once the user has
  // natively maximized/resized the window larger than its compact toolbar
  // footprint — there is no in-app expand control anymore, so this tracks
  // the OS window state directly instead of app state.
  useEffect(() => {
    const appWindow = getCurrentWindow();
    appWindow.isMaximized().then(setIsMaximized).catch(() => {});
    const unlisten = appWindow.onResized(() => {
      appWindow.isMaximized().then(setIsMaximized).catch(() => {});
    });
    return () => {
      unlisten.then((f) => f());
    };
  }, []);

  // The main window is `transparent: true` (tauri.conf.json) so the extra
  // height it grows into for an open header dropdown is genuinely
  // see-through rather than a visible grey panel — see App.css's
  // `.compact-transparent` rule. That transparency only makes sense in the
  // compact toolbar state (maximized view wants its normal opaque
  // background), so this marks/unmarks html+body the same way main.tsx
  // marks overlay windows, rather than via CSS :has().
  useEffect(() => {
    document.documentElement.classList.toggle("compact-transparent", !isMaximized);
    document.body.classList.toggle("compact-transparent", !isMaximized);
  }, [isMaximized]);

  // The overlay window (Interview/Meeting) and this main window are separate
  // webviews with no shared React state — ending a session from inside the
  // overlay (its own ✕ / "Yes, end interview" / Escape) has no way to reset
  // this window's Start/Stop button back to idle on its own. The Rust side
  // emits this event whenever an overlay closes, from whichever side
  // triggered it, so this listener is what keeps the two in sync instead of
  // requiring a redundant click on Stop here after already ending it there.
  useEffect(() => {
    const unlisten = listen("interview-mode:overlay-closed", () => {
      setSessionState("IDLE");
    });
    return () => {
      unlisten.then((f) => f());
    };
  }, []);

  // HeaderDropdown itself measures its real rendered height and resizes the
  // main window to match exactly on mount, then shrinks it back to 56px on
  // unmount (see HeaderDropdown.tsx) — so toggling here is just React
  // state; no resize call needed at this layer.
  const togglePopover = useCallback((p: Exclude<Popover, null>) => {
    setOpenPopover((cur) => (cur === p ? null : p));
  }, []);

  const closePopover = useCallback(() => setOpenPopover(null), []);

  const startInterview = useCallback(async () => {
    const overlaySettings = loadOverlaySettings();
    saveOverlaySettings({ ...overlaySettings, ...answerStyleToOverlayFields(overlaySettings.answerStyle) });

    uploadDocumentContext(INTERVIEW_CONTEXT_SECTIONS, interviewContext);

    await (prewarmRef.current ??
      invoke("start_system_audio_capture").catch((e) => {
        if (String(e) !== "capture already running") throw e;
      }));
    await invoke("clear_transcript").catch(() => {});
    await invoke("show_interview_overlay");
  }, [interviewContext]);

  const startMeeting = useCallback(async () => {
    window.localStorage.setItem(
      "meeting-mode:active-meeting",
      JSON.stringify({ meetingTitle: meetingTitle.trim(), participants: meetingParticipants.trim() }),
    );

    uploadDocumentContext(MEETING_CONTEXT_SECTIONS, meetingContext);

    await invoke("clear_meeting_session").catch(() => {});
    await (prewarmRef.current ??
      invoke("start_system_audio_capture").catch((e) => {
        if (String(e) !== "capture already running") throw e;
      }));
    await invoke("show_meeting_overlay");
  }, [meetingContext, meetingTitle, meetingParticipants]);

  const handleStart = useCallback(async () => {
    setError(null);
    setSessionState("STARTING");
    closePopover();
    try {
      if (mode === "INTERVIEW") {
        await startInterview();
      } else {
        await startMeeting();
      }
      setSessionState("LISTENING");
    } catch (e) {
      setError(String(e));
      setSessionState("IDLE");
    }
  }, [mode, startInterview, startMeeting, closePopover]);

  const handleStop = useCallback(async () => {
    try {
      if (mode === "INTERVIEW") {
        await invoke("hide_interview_overlay");
      } else {
        await invoke("hide_meeting_overlay");
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setSessionState("IDLE");
    }
  }, [mode]);

  const startLabel =
    sessionState === "STARTING" ? "Starting…" : sessionState === "LISTENING" ? "Listening" : "Start";

  return (
    <main className={`app-shell ${isMaximized ? "" : "app-shell-compact"}`}>
      <header className="compact-header">
        <div className="compact-header-brand">
          <img className="header-logo" src={smallbirdLogo} alt="Smallbird" />
          <span className="header-product">SmallBird</span>
        </div>

        <div className="compact-header-controls">
          <div className="dropdown-anchor">
            <button
              className="compact-header-btn"
              onClick={() => togglePopover("MODE")}
              disabled={sessionState !== "IDLE"}
              aria-haspopup="menu"
              aria-expanded={openPopover === "MODE"}
            >
              <span>Mode: {MODE_LABELS[mode]}</span>
              <IconChevronDown />
            </button>
            {openPopover === "MODE" && (
              <HeaderDropdown onClose={closePopover} className="header-dropdown-menu header-dropdown-mode">
                <div role="menu">
                  {(["INTERVIEW", "MEETING"] as Mode[]).map((m) => (
                    <button
                      key={m}
                      role="menuitemradio"
                      aria-checked={mode === m}
                      className={`dropdown-item${mode === m ? " active" : ""}`}
                      onClick={() => {
                        setMode(m);
                        closePopover();
                      }}
                    >
                      {MODE_LABELS[m]}
                    </button>
                  ))}
                </div>
              </HeaderDropdown>
            )}
          </div>

          <div className="dropdown-anchor">
            <button
              className="compact-header-btn icon"
              onClick={() => togglePopover("CONTEXT")}
              title="Context"
              aria-haspopup="dialog"
              aria-expanded={openPopover === "CONTEXT"}
            >
              <IconAttachment />
              <span>Context</span>
            </button>
            {openPopover === "CONTEXT" && (
              <HeaderDropdown onClose={closePopover} className="header-dropdown-panel header-dropdown-wide">
                <div className="popover-overlay">
                  <div className="popover" role="dialog" aria-label="Context">
                    <div className="popover-header">
                      <span className="setup-section-label">Attach context</span>
                      <button className="modal-close-btn" onClick={closePopover} aria-label="Close">
                        ✕
                      </button>
                    </div>
                    <div className="popover-body">
                      {mode === "MEETING" && (
                        <div className="setup-identity">
                          <div className="setup-identity-field">
                            <label htmlFor="meeting-title">Meeting Title</label>
                            <input
                              id="meeting-title"
                              className="setup-input"
                              value={meetingTitle}
                              onChange={(e) => setMeetingTitle(e.target.value)}
                              placeholder="e.g. Q3 Roadmap Review"
                            />
                          </div>
                          <div className="setup-identity-field">
                            <label htmlFor="meeting-participants">Participants</label>
                            <input
                              id="meeting-participants"
                              className="setup-input"
                              value={meetingParticipants}
                              onChange={(e) => setMeetingParticipants(e.target.value)}
                              placeholder="e.g. Alex, Priya, Sam"
                            />
                          </div>
                        </div>
                      )}
                      <DocumentContext
                        sections={mode === "INTERVIEW" ? INTERVIEW_CONTEXT_SECTIONS : MEETING_CONTEXT_SECTIONS}
                        state={mode === "INTERVIEW" ? interviewContext : meetingContext}
                        onChange={mode === "INTERVIEW" ? setInterviewContext : setMeetingContext}
                      />
                    </div>
                  </div>
                </div>
              </HeaderDropdown>
            )}
          </div>

          {sessionState === "LISTENING" ? (
            <Button variant="danger" onClick={handleStop}>
              Stop
            </Button>
          ) : (
            <Button variant="primary" onClick={handleStart} disabled={sessionState === "STARTING"}>
              {startLabel}
            </Button>
          )}

          <div className="dropdown-anchor">
            <button
              className="compact-header-btn icon"
              onClick={() => togglePopover("SETTINGS")}
              title="Settings"
              aria-label="Settings"
              aria-haspopup="dialog"
              aria-expanded={openPopover === "SETTINGS"}
            >
              <IconSettings />
            </button>
            {openPopover === "SETTINGS" && (
              <HeaderDropdown onClose={closePopover} className="header-dropdown-panel header-dropdown-settings">
                <SettingsPopover onClose={closePopover} />
              </HeaderDropdown>
            )}
          </div>

          <div className="dropdown-anchor">
            <button
              className="compact-header-btn icon"
              onClick={() => togglePopover("ACCOUNT")}
              title="Account"
              aria-label="Account"
              aria-haspopup="dialog"
              aria-expanded={openPopover === "ACCOUNT"}
            >
              <IconAccount />
            </button>
            {openPopover === "ACCOUNT" && (
              <HeaderDropdown onClose={closePopover} className="header-dropdown-panel">
                <Account onClose={closePopover} />
              </HeaderDropdown>
            )}
          </div>
        </div>
      </header>

      {error && <p className="error compact-header-error">{error}</p>}

      {isMaximized && (
        <div className="expanded-content">
          <UpdateBanner />
          <LowEndHardwareBanner />
          {mode === "INTERVIEW" ? (
            <InterviewHistory refreshKey={historyRefreshKey} />
          ) : (
            <MeetingHistory refreshKey={historyRefreshKey} />
          )}
        </div>
      )}
    </main>
  );
}

export default App;
