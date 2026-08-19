# Progress Log

Phase 1 definition of done tracked against `docs/architecture.md`. Order follows the
required development steps.

## Step 1 — Environment inspection

**Status: Done (2026-08-14)**

- Windows 11 Home Single Language, build 26200.
- Node v24.12.0, npm 11.6.2.
- Rust 1.97.1 stable-x86_64-pc-windows-msvc, Cargo 1.97.1.
- Python 3.12.10 — only reachable via `py -3`; bare `python`/`python3` resolve to the
  Microsoft Store app-execution-alias stub and must not be used in scripts.
- VS Build Tools 2022 with C++ (VC.Tools.x86.x64) component installed — required for
  MSVC linking.
- CMake present.
- Git present.
- Tauri CLI: not installed — will install via npm dev dependency during Step 2.
- PocketSphinx: no system library, no Python package installed. Full detail in Step 4.

Full table recorded in `docs/architecture.md`.

## Step 2 — Tauri + React + Rust shell

**Status: Done (2026-08-14)**

- Scaffolded via `npm create tauri-app@latest desktop -- --template react-ts` into
  `apps/desktop`.
- Renamed product to "Interview Assistant", identifier `com.interviewassistant.desktop`,
  default window 1100x760 (min 900x600).
- `cargo check` in `apps/desktop/src-tauri` compiles cleanly (Rust 1.97.1, MSVC target).
- `npm run tauri dev` builds and launches `target\debug\desktop.exe` successfully —
  verified the process is running (confirmed via `tasklist`) after a ~45s dev build.
- Gotcha hit during verification: backgrounding `npm run tauri dev` via `nohup ... &`
  did not get tracked correctly by the shell tool (reported false "exited with code 0"
  while the Vite/cargo processes kept running detached), which left port 1420 and a
  stale build-directory lock occupied on the next attempt ("Blocking waiting for file
  lock on build directory"). Fixed by using the Bash tool's native `run_in_background`
  flag (which tracks the process correctly) and by killing stray `cargo.exe`/`vite`
  processes via `taskkill` before retrying. Recorded here so future dev-server restarts
  in this repo know to check `tasklist`/`netstat` for leftovers first.

## Step 3 — WASAPI system-audio capture

**Status: Done (2026-08-14)**

- Chose the `wasapi` crate (HEnquist/wasapi-rs, v0.24.0) over `cpal` — `cpal` has no
  built-in support for WASAPI loopback capture of the default render/output device,
  which is the whole point of "system audio" capture. `wasapi` exposes
  `AudioClient::initialize_client` which automatically sets `AUDCLNT_STREAMFLAGS_LOOPBACK`
  when you open a `Direction::Capture` client against a `Direction::Render` (output)
  device in shared mode — exactly the classic loopback pattern.
- Implemented in `apps/desktop/src-tauri/src/audio/`:
  - `system_capture.rs` — `SystemAudioCapture::start()` spawns a dedicated OS thread,
    opens the default output device in loopback mode (`StreamMode::EventsShared` with
    `autoconvert: true`), reads packets via `AudioCaptureClient::read_from_device`,
    resamples to 16kHz mono, computes RMS, and pushes `AudioChunk`s over a
    `crossbeam-channel`.
  - `mic_capture.rs` — mirrors system capture but opens the default `Direction::Capture`
    (microphone) device. Present per the required `AudioCapture` module shape but not
    yet wired into any Tauri command (system audio is the Phase 1 primary source, per
    spec). Currently unused — dead-code warnings are expected until Step 4 wires it in
    alongside the STT pipeline.
  - `device_manager.rs` — `AudioDeviceManager::list_output_devices` /
    `list_input_devices`, for future Settings device pickers.
  - `resample.rs` — `AudioResampler` wraps `rubato::FftFixedIn` to downmix to mono and
    resample from the device's native mix rate (typically 44.1/48kHz) to 16kHz.
- `rubato` gotcha: latest crates.io version is 5.0.0, which replaced the classic
  `FftFixedIn`/`Resampler::process(&[Vec<f32>], ...)` API with a new
  `audioadapter`-buffer-based `Fft`/`FixedSync` API. Pinned to `rubato = "0.15"`
  instead of chasing the rewrite, since 0.15's API is stable and sufficient here.
- Tauri commands added (`commands.rs`): `start_system_audio_capture`,
  `stop_audio_capture`, `list_output_devices`, `list_input_devices`.
  `start_system_audio_capture` spawns the capture thread and a forwarding thread that
  emits `audio:level` events (`{ source, rms_level }`) to the frontend.
- Frontend (`App.tsx`): minimal Start/Stop Recording UI with a live level-meter bar
  driven by `audio:level` events, replacing the Tauri/React/Vite boilerplate greet demo.
- **Manually verified by the user**: launched `npm run tauri dev`, clicked
  START RECORDING, played audio, and confirmed the level meter reacts live. Confirms
  the full path System Audio → WASAPI loopback → resample → RMS → Tauri event → React
  UI works on this machine.
- Process-management gotcha (same class as Step 2's): always check
  `tasklist "IMAGENAME eq desktop.exe"` / `cargo.exe` / `netstat -ano | findstr 1420`
  before starting a new `npm run tauri dev`, and kill stragglers first — otherwise the
  new run blocks on "waiting for file lock on build directory" or fails with
  "Port 1420 is already in use".

## Step 4 — PocketSphinx integration

**Status: In progress — architecture decided (2026-08-14)**

Investigated three options for getting CMU PocketSphinx into the Rust/Tauri process:

1. **`pocketsphinx-sys` / `pocketsphinx-rs` (kriomant)** — the only Rust FFI bindings
   that exist on crates.io/GitHub. Rejected: ~10 years unmaintained, targets the old
   CMU Sphinx C API via `pkg-config` (awkward on Windows/MSVC), and the modern
   `cmusphinx/pocketsphinx` 5.x library these would need to link against has a
   different API surface than what those bindings were generated for. High risk of
   days of bindgen/linker debugging for an unmaintained crate.
2. **bindgen a fresh FFI against `libpocketsphinx` C API ourselves** — technically
   possible (CMake + `BUILD_SHARED_LIBS=ON` builds a Windows DLL) but a substantial,
   fragile undertaking: hand-rolling safe Rust wrappers around the C decoder API,
   managing the native library's build/link in `build.rs`, and keeping it working
   across Rust/MSVC toolchain updates. Rejected for Phase 1 given the scope budget.
3. **Local sidecar process running the official Python `pocketsphinx` package** —
   chosen. `pip install pocketsphinx` builds and installs cleanly on this machine
   (confirmed: `pocketsphinx-5.1.1`, built from source via CMake, ships the `en-us`
   acoustic/language model in-package). Verified end-to-end: `Decoder` construction,
   streaming `process_raw()`, and `hyp()` retrieval all work. Rust spawns this as a
   child process (`std::process::Command`, no shell) and communicates over stdin/stdout
   using a small line-delimited JSON protocol; audio bytes go in, transcript events
   come out. This still satisfies every hard requirement: STT runs entirely on the
   user's machine, it's the traditional/non-neural PocketSphinx engine (no Whisper/
   cloud/neural ASR), and the *backend* (FastAPI) never sees audio — the sidecar is a
   local child process of the desktop app, not a network service.

This decision keeps the Rust side simple (spawn/pipe/kill a subprocess) and puts the
actual PocketSphinx API usage in Python, where the package is well-documented and
actively maintained, at the cost of one extra local process during recording. If a
maintained Rust binding appears later, the sidecar can be swapped for in-process FFI
without changing the Tauri command surface (`stt` module keeps the same
`SttEngine`-shaped interface either way).

Sidecar location: `packages/stt/pocketsphinx_sidecar/` (Python). Rust integration:
`apps/desktop/src-tauri/src/stt/`.

**Sidecar verified working (2026-08-14).** Protocol: length-prefixed PCM16 mono
16kHz frames in on stdin, JSON-lines events out on stdout (`ready`/`partial`/`final`/
`error`). Uses `pocketsphinx.Endpointer` (energy/VAD-based speech boundary detection —
signal processing, not semantic question detection) to decide utterance boundaries,
and a streaming `Decoder` for partial/final hypotheses.

Tested with a real spoken utterance generated via Windows SAPI TTS at 16kHz mono
("Can you explain the architecture of the system you built"). Result: streaming
partials progressively refined and the finalized transcript was
"can you explain the architecture of the system you build" — a strong match,
confirming the decode pipeline (endpointing → streaming decode → finalization) works
correctly end-to-end, not just that the process doesn't crash.

Important gotcha found and fixed during testing: a naive test harness that writes all
audio to the sidecar's stdin before reading any of its stdout deadlocks on Windows
once the OS pipe buffer fills (sidecar blocks writing JSON events that nobody is
draining, so it stops reading stdin, so the writer's `stdin.write()` eventually fails
with `OSError: [Errno 22] Invalid argument`). The Rust sidecar wrapper must read
stdout on a dedicated thread concurrently with writing stdin — never write-then-read
sequentially against a child process pipe.

**Rust integration complete and verified end-to-end (2026-08-14).**

- `apps/desktop/src-tauri/src/stt/`:
  - `sidecar.rs` — `SttSidecar::spawn()` locates a Python interpreter (`py -3` first,
    falls back to `python`, since bare `python`/`python3` resolve to a non-functional
    Microsoft Store stub on this machine — see Step 1), spawns
    `packages/stt/pocketsphinx_sidecar/sidecar.py` as a child process, and starts a
    dedicated stdout-reading thread that parses each JSON line and forwards it as an
    `SttEvent` over an `mpsc::Sender`. `send_samples()` converts f32 audio to PCM16
    and writes it using the length-prefixed frame protocol; `flush()` sends the
    zero-length end-of-utterance marker. Implements `Drop` to force-kill the child
    process as a safety net if `shutdown()` is never called (e.g. a panic) — Windows
    does not kill child processes when a parent exits, so without this an unclean
    Rust-side exit would orphan the Python sidecar.
  - `events.rs` — `SttEvent`/`SttEventKind` (Partial/Final) plus the private
    `SidecarLine` enum matching the sidecar's JSON shape via serde's internally
    tagged `type` field.
- `apps/desktop/src-tauri/src/transcript/mod.rs` — `TranscriptManager` per spec
  section 8: keeps one in-progress `TranscriptSegment` per `AudioSource`, promotes it
  into the `InterviewSession.segments` list on a `Final` STT event. No component
  anywhere in this pipeline classifies text as a question or decides when to call an
  LLM — confirmed by design, matching the "no QuestionDetector" requirement.
- `commands.rs` rewired: `start_system_audio_capture` now starts three cooperating
  threads — WASAPI capture, an STT-events-forwarder thread (drains the sidecar's
  `SttEvent`s, applies them to `TranscriptManager`, emits `transcript:update` to the
  frontend), and a pipeline thread that forwards captured audio to both the sidecar
  (`send_samples`) and the UI (`audio:level`). `stop_audio_capture` signals the audio
  thread to stop, which closes the channel the pipeline thread reads from, which
  flushes+shuts down the sidecar, which closes its stdout and lets the events thread
  exit — a clean cascade with no polling.
- Frontend (`App.tsx`): added a scrolling "Interview Transcript" panel listening for
  `transcript:update` events — finalized segments accumulate as timestamped entries,
  the current in-progress partial renders as an italicized "live" line below them.
- **Manually verified by the user**: started recording, played audio with clear
  speech, and confirmed transcribed text appeared in the transcript panel and
  reasonably matched what was said. This validates the complete local pipeline:
  System Audio → WASAPI loopback → resample → PocketSphinx sidecar (endpointing +
  streaming decode) → TranscriptManager → Tauri event → React UI.
- Process-management note: killing the desktop app via an external `taskkill /F`
  (as opposed to using the STOP RECORDING button, which goes through the graceful
  `stop_audio_capture` → sidecar `shutdown()` path) can orphan the Python sidecar
  process, since Windows does not cascade-kill child processes. This was observed
  once during dev testing (killed `desktop.exe` directly while iterating) and is
  mitigated by the `Drop` impl for in-process exits, but an external force-kill of
  the whole app is outside what any in-process Rust code can intercept — this is a
  general Windows characteristic, not a bug specific to this app. Documented here so
  future dev-loop restarts know to check `tasklist "IMAGENAME eq python.exe"` too,
  not just `desktop.exe`/`cargo.exe`.

## Step 5 — TranscriptManager

**Status: Done (2026-08-14, built as part of Step 4)**

`TranscriptManager`/`InterviewSession`/`TranscriptSegment` were implemented and
verified alongside the PocketSphinx sidecar integration — see the Step 4 section
above for full detail. Extended further below (this Step 5/6/7 pass) with
`RecordingState`, pause/resume timing (`paused_ms_total`, `elapsed_ms()`), and
`mark_paused`/`mark_resumed`/`mark_stopped` lifecycle methods.

## Step 6 — Recording controls (Start/Pause/Resume/Stop) & Transcript Experience

**Status: Done (2026-08-14) — tested and manually verified by the user**

### What was implemented

**State machine (Rust, `apps/desktop/src-tauri/src`):**

- `transcript::RecordingState` enum: `Idle | Recording | Paused | Stopped`, `Copy`
  + `Serialize` so it can be pushed to the frontend directly as a Tauri event
  payload (`recording:state`, emitted on every transition).
- `audio::PauseSignal` — a second atomic flag alongside the existing `StopSignal`.
  Deliberately *not* implemented as "stop WASAPI capture" — the capture thread
  keeps running and draining the OS audio buffer while paused (so the buffer never
  overflows and resume is instant), but the pipeline thread checks
  `pause_signal.is_paused()` on every captured chunk and, while true, skips both
  forwarding audio to the PocketSphinx sidecar and emitting the `audio:level` UI
  event. This satisfies "preserve the existing transcript" / "do not destroy the
  STT session unnecessarily" literally: the sidecar process is never touched by
  pause/resume, only the audio reaching it is gated.
- `InterviewSession` gained `ended_at_ms`, `paused_ms_total`, and a (non-serialized)
  `pause_started_at_ms`. `elapsed_ms()` computes wall-clock-minus-paused-time, and
  freezes at the pause timestamp while actively paused rather than continuing to
  advance — this is what makes the frontend timer able to "freeze" without needing
  its own separate source of truth for the freeze point.
- Five new/changed Tauri commands in `commands.rs`: `pause_recording`,
  `resume_recording` (both validate the current `RecordingState` and reject
  invalid transitions, e.g. pausing when not `Recording`), `stop_audio_capture`
  (now also calls `transcript.mark_stopped()` and emits the `Stopped` state),
  `get_recording_state`, `start_new_interview` (resets `AppState` back to `Idle`
  and clears the transcript; rejects being called while `Recording`/`Paused`).

**Frontend (`apps/desktop/src`):**

- `types.ts` — shared TS types for `RecordingState`, `TranscriptSegment`,
  `InterviewSession`, event payloads, matching the Rust serde shapes.
- `App.tsx` rewritten around the four-state machine. A `setInterval`-driven timer
  (250ms tick) computes elapsed time client-side from a session-start timestamp
  ref, a running paused-accumulator ref, and a pause-start ref — mirroring the
  Rust-side `elapsed_ms()` logic so the displayed timer freezes on pause and
  resumes correctly without drifting from what a subsequent `get_current_session`
  call would report. Renders three states of the control row (Idle → Start;
  Recording → Pause + Stop; Paused → Resume + Stop) and disables Clear/other
  destructive actions while a recording is in flight.
- `TranscriptPanel.tsx` extracted as its own component (Step 6's "Transcript
  Experience" requirements): finalized segments are keyed by their stable
  `segment.id` (assigned once in Rust when the segment is created, unchanged
  across partial→final transitions is not applicable since partials use a
  different in-memory representation — see "no duplication" below), auto-scrolls
  only while `isRecording || isPaused` (not once stopped, so the user can freely
  scroll the finished transcript), and renders the live partial as a visually
  distinct italic "live" row that is replaced (never appended) on every partial
  update.
- **No-duplication guarding**: the `transcript:update` listener in `App.tsx`
  checks `prev.some(s => s.id === segment.id)` before appending a finalized
  segment and replaces-in-place if it ever sees the same id twice (defensive; in
  practice each id is only emitted once as `Final`, since `TranscriptManager`
  removes the in-progress segment from its map on finalization). Partial text
  updates go into a single `livePartial` string state, never an array, so a
  fast-changing partial can never flicker/duplicate as separate DOM rows.

### Post-stop summary screen (spec section 5/10)

`App.tsx`'s `isStopped` branch renders the "Recording Complete" card: Duration
(from the same timer state, frozen at stop), transcript word/empty status, and
four actions — **Analyze Interview** (rendered `disabled`, tooltip explains it's
not implemented yet — intentionally not wired to any backend call, per the
constraint that Steps 5-7 must not call FastAPI/RAG/LLM), **Export TXT**,
**Export JSON**, **Start New Interview**.

### Tests performed (manual, in the running dev app)

All of the following were run against the actual built app (`npm run tauri dev`,
`target\debug\desktop.exe`), not just compiled:

1. **Start → play audio → Pause → verify frozen timer/quiet meter → Resume →
   verify timer continues and transcription resumes → Stop → summary screen with
   correct Duration and transcript.** User-confirmed: "All worked as expected."
2. **Start → Stop with no audio played (empty recording).** User-confirmed:
   reached the summary screen showing "Transcript: Empty" without error/crash.
3. **Start New Interview → verify reset → start a second full recording.**
   User-confirmed: state reset cleanly and a second session recorded normally
   (validates `AppState`/`TranscriptManager` are correctly cleared between runs,
   not just on first launch).
4. Export TXT and Export JSON from the summary screen, opening a native Windows
   save dialog (`tauri-plugin-dialog`), writing the file, and opening the saved
   files to inspect content. User-confirmed: both dialogs appeared, files saved,
   and content was correct — readable transcript in TXT, valid structured JSON
   with segments/timestamps in JSON.

Not separately re-tested in this pass (already covered in Step 4's verification
and unchanged by this work): raw WASAPI capture and PocketSphinx transcription
accuracy itself.

### Known limitations / not covered

- **STT sidecar failure and audio device disconnect mid-recording** were not
  explicitly fault-injected in this pass (e.g. unplugging the output device, or
  killing the Python sidecar process externally while recording). The pipeline is
  structured to degrade reasonably — `sidecar.send_samples()` errors are logged
  and swallowed rather than crashing the pipeline thread, and WASAPI errors inside
  the capture loop already used `Result`/early-return patterns from Step 3/4 — but
  this has not been exercised under this task's test matrix and should be
  explicitly fault-injected before Phase 1 is considered fully done.
- **"Application closing during recording"**: closing the window while recording
  is active was not explicitly tested in this pass. The `SttSidecar` `Drop` impl
  (added in Step 4) force-kills the child Python process on an unclean Rust-side
  exit, and WASAPI capture threads are daemon-style (not explicitly joined on
  window close), so no explicit shutdown hook exists yet for "user closes the
  window mid-recording" — worth adding a `tauri::WindowEvent::CloseRequested`
  handler that calls the same stop path as the Stop button, in a later pass.
- Pause/resume was only tested once per session in the manual pass (not multiple
  pause/resume cycles within one recording). The underlying mechanism (an atomic
  flag checked per-chunk) has no state that would make repeated cycles behave
  differently, so this is a low-risk gap, not a known bug.
- No automated/unit tests were added for the new Rust state-machine logic
  (`elapsed_ms()`, pause/resume transition validation) or the frontend timer
  math — all verification in this pass was manual, end-to-end, in the running
  app, per the user's explicit test-plan.

## Step 7 — Transcript storage/export

**Status: Done (2026-08-14) — see Step 6 above for implementation + test detail**

Implemented as part of the same pass as Step 6 (`export_transcript_txt` /
`export_transcript_json` commands in `commands.rs`, native save dialog via
`tauri-plugin-dialog`). Both formats match the spec's example shapes:

- **TXT**: header block (session ID, started/ended ISO-ish timestamps, duration,
  word count) followed by `[MM:SS]` or `[HH:MM:SS]` relative-timestamp-prefixed
  paragraphs, one per finalized segment.
- **JSON**: `{ sessionId, startedAt, endedAt, durationMs, wordCount, segments: [{
  timestamp, source, text }] }` — matches the requested shape (the spec's example
  used `duration`; used `durationMs` here for clarity on units, and added
  `wordCount` as a useful extra field; `segments[].timestamp` is each segment's
  absolute finalization time in the same lightweight ISO-ish format as
  `startedAt`/`endedAt`, not the session-relative `[MM:SS]` used in the TXT
  export).
- Timestamp format note: `iso8601()` in `commands.rs` is a deliberately minimal,
  dependency-free `"<unix-seconds>.<millis>Z"` string — not calendar-date ISO
  8601 — to avoid pulling in a full date/time crate for Phase 1 file-header
  metadata. If human-readable calendar dates in exports matter later, swap this
  for the `time` or `chrono` crate.
- Both export commands only run when the user clicks Export TXT/Export JSON from
  the post-stop summary screen; nothing is written or uploaded automatically, and
  no network call is made anywhere in the export path — confirmed by reading the
  implementation (`write_file` is a plain `std::fs::File::create` call) and by
  the user's manual test opening the resulting files locally.

## Step 8 — FastAPI backend

**Status: Done (2026-08-14) — tested and manually verified by the user**

### What was implemented

**Backend (`apps/backend/`, Python 3.12 + FastAPI + Uvicorn + Pydantic v2 + pytest + httpx):**

- `app/main.py` — app factory. Registers CORS middleware (explicit allowlist of
  Tauri dev/prod origins — `http://localhost:1420`, `http://127.0.0.1:1420`,
  `tauri://localhost`, `https://tauri.localhost` — never `"*"`, per spec section
  12), a `RequestValidationError` handler that reshapes FastAPI's default 422 body
  into the spec's `{ error: { code, message } }` format, and a catch-all exception
  handler returning 500 in the same shape without leaking internals.
- `app/core/config.py` — `Settings`/`get_settings()`, reads `BACKEND_HOST`,
  `BACKEND_PORT`, `CORS_ALLOW_ORIGINS`, `LLM_PROVIDER`, `LLM_MODEL`, `LOG_LEVEL`
  from the environment. No secrets hard-coded.
- `app/schemas/interview.py` — `InterviewAnalysisRequest`, `Transcript`,
  `TranscriptSegment`, `CandidateContext`, `TranscriptSource` (strict enum:
  `SYSTEM_AUDIO` | `MICROPHONE` only — arbitrary source strings are rejected with
  422, not silently accepted). Validates timestamp format (`MM:SS`/`HH:MM:SS`),
  non-blank segment text, length caps on resume/job description/project names
  (defends against unbounded-payload abuse without being restrictive for real
  interview-length transcripts), and duration bounds.
- `app/schemas/analysis.py` — `AnalysisResponse`, `AnalysisStatus`.
- `app/schemas/error.py` — `ErrorDetail`/`ErrorResponse` matching the spec's
  `{ error: { code, message } }` shape exactly.
- `app/services/analysis_service.py` — `AnalysisProvider` ABC,
  `MockAnalysisProvider` (the only implementation wired up; always returns
  `overall_score=0`, `technical_score=0`, `communication_score=0`, empty
  strengths/improvements/questions lists, and a message explicitly stating real
  LLM analysis isn't connected yet — a unit test
  (`test_response_never_reflects_fabricated_scores`) guards against this ever
  silently changing), `AnalysisService` (thin dispatcher, structured so a future
  `LLMAnalysisProvider` slots in without touching the route).
- `app/services/interview_service.py` — `log_incoming_request()`: logs
  `session_id`, segment count, and duration only — never transcript text, resume
  content, or any other request body content.
- `app/api/routes/health.py` — `GET /health`.
- `app/api/routes/interviews.py` — `POST /interviews/analyze` (mounted under
  `/api/v1` by `app/api/router.py`, giving the full path
  `POST /api/v1/interviews/analyze` per spec section 11's versioning requirement).
- Structured logging matches the spec's example format exactly: `[API]`,
  `[INTERVIEW]`, `[TRANSCRIPT]`, `[ANALYSIS]` prefixed lines — verified against
  live server output (see Tests below).

**Desktop (`apps/desktop/src-tauri/src/backend/`, Rust):**

- `config.rs` — `backend_url()` reads `BACKEND_URL` env var, defaults to
  `http://127.0.0.1:8000`. No production URL hard-coded anywhere.
- `types.rs` — wire types (`InterviewAnalysisRequest`, `WireTranscript`,
  `WireTranscriptSegment`, `WireAudioSource`, `AnalysisResponse`, `ErrorResponse`)
  matching the backend's Pydantic schemas field-for-field, including the
  `SCREAMING_SNAKE_CASE` source enum and `MM:SS`/`HH:MM:SS` timestamp string
  format (converted from the desktop's internal millisecond timestamps by
  `commands.rs::format_relative_timestamp`).
- `client.rs` — `BackendClient` wraps `reqwest` (added with `--no-default-features
  --features json` only — no TLS backend at all, since Phase 1 only ever talks
  plain HTTP to `127.0.0.1`, keeping the dependency tree meaningfully smaller than
  pulling in rustls/native-tls for a local-only connection). `health_check()` (3s
  timeout, used for the UI connectivity indicator) and `analyze()` (30s timeout,
  parses the `{error:{code,message}}` shape on non-2xx responses so the UI can
  show a real backend-reported error message rather than a generic HTTP status).
- `commands.rs` — two new Tauri commands: `check_backend_connection` (liveness
  probe only, never touches the transcript) and `analyze_interview` (builds the
  wire request from the current `TranscriptManager` session — filters to only
  finalized segments, so no partial/in-progress text is ever sent — and rejects
  with an error if the transcript is empty, before ever making an HTTP call).

**Desktop (`apps/desktop/src`, React/TS):**

- `types.ts` — added `BackendStatus`, `AnalysisPhase`, `AnalysisResponse` types.
- `App.tsx` — polls `check_backend_connection` on mount and every 10s
  (`BACKEND_POLL_INTERVAL_MS`), driving a `Backend: Connected/Offline/Connecting…`
  indicator in the header (spec section 9's required connection states — `Unknown`
  is shown as "Checking…" before the first probe resolves). The "Analyze
  Interview" button is disabled while the backend is `OFFLINE` or an empty
  transcript, showing "Analyzing…" during the request and rendering
  "Uploading transcript... / Preparing analysis..." progress text (spec section
  10) while in flight. Failures render inline (`Analysis failed: <message>`)
  without crashing the app — verified live by taking the backend down mid-session.
- `AnalysisResult.tsx` — new component for the post-analysis card. Deliberately
  renders `—` for Technical/Communication/Overall scores rather than the raw `0`
  the mock backend returns: the spec explicitly says "Do not create fake scores,"
  and a bare `0/100` would read as a real (very bad) score rather than
  "not computed yet." The response's own `message` field (explaining LLM
  analysis isn't connected) is shown verbatim below the scores.

### Tests performed

**Backend automated tests** (`apps/backend/tests/`, run via
`.venv/Scripts/python.exe -m pytest`): 12 tests, all passing —
`test_health.py` (health check shape), `test_interviews.py` (valid request → 200
with correct mock shape; missing transcript → 422; invalid source → 422; empty
segments → 200; missing session_id → 422; blank segment text → 422; malformed
timestamp → 422; negative duration → 422; a 2000-segment/7200s "large transcript"
→ 200, exercising the spec's explicit large-transcript requirement; minimal
payload with only required fields → 200; and a regression guard asserting the
mock response never reports non-zero scores).

**Backend live-server verification** (`uvicorn app.main:app --port 8000`, hit with
`curl`): `GET /health` → `200 {"status":"ok","service":"whitedotai-backend"}`;
valid `POST /api/v1/interviews/analyze` → `200` with the exact mock shape;
missing-transcript and invalid-source requests → `422` with the
`{"error":{"code":"VALIDATION_ERROR","message":"..."}}` shape; a CORS preflight
`OPTIONS` request from `Origin: http://localhost:1420` → `200` with
`access-control-allow-origin: http://localhost:1420` (confirms the Tauri dev
origin is allowed and the config isn't accidentally wildcard-open); log output
inspected directly and confirmed to match the spec's `[API]`/`[INTERVIEW]`/
`[TRANSCRIPT]`/`[ANALYSIS]` format with no transcript/secret content.

**Full desktop+backend integration** (manual, in the running Tauri dev app, user-
confirmed at each step):
1. With the backend running, the header's Backend indicator showed "Connected"
   (green dot) — confirms `check_backend_connection` → `health_check()` →
   `GET /health` works end-to-end through Tauri's async command layer.
2. Full flow: Start Recording → play audio → Stop Recording → click
   "ANALYZE INTERVIEW" on the summary screen → briefly saw the
   "Analyzing Interview... / Uploading transcript... / Preparing analysis..."
   progress state → the "Interview Analysis" card appeared with
   `Status: completed`, dash-scores, and the correct "next phase" message.
   Repeated twice by the user; backend logs (inspected directly) show both
   requests landing with correct `segments=5 duration=21` /
   `segments=5 duration=35` metadata and nothing else — confirming no audio and
   no raw transcript text is logged, only counts/durations.
3. Offline resilience: backend process stopped mid-session while the desktop app
   stayed open. Within the 10s poll interval the indicator flipped to "Offline"
   (red dot), and the rest of the app (transcript view, recording controls)
   remained fully responsive — no crash, no frozen UI, confirming
   `check_backend_connection`'s error path and the "Analyze Interview" button's
   `OFFLINE`-disables-the-button logic both work as intended.
4. Regression check: backend `pytest` suite re-run after all desktop-side changes
   — still 12/12 passing, confirming the backend wasn't broken by the desktop
   integration work (it can't be, since the desktop only calls it over HTTP, but
   verified explicitly per the task's "Existing Steps 1-7 still work" /
   regression-safety requirement).

Not independently re-verified in this pass (unchanged since Step 4-7 and not
touched by this work): raw WASAPI capture, PocketSphinx transcription accuracy,
pause/resume timer behavior, TXT/JSON export. No regression is expected since none
of Step 8's code touches the audio/STT/transcript pipeline — `analyze_interview`
only *reads* the existing `TranscriptManager` session after recording has already
stopped.

### Known issues / limitations

- The `candidate_context` (resume/projects) field is defined end-to-end
  (Pydantic schema, Rust wire type) but never populated from the UI yet — there
  is no resume/JD upload feature in the desktop app yet (that's Step 9, RAG/
  document upload, explicitly out of scope for Step 8). `analyze_interview`
  currently always sends `candidate_context: None`.
  - Similarly, `role`/`company`/`job_description` are wired as optional Tauri
    command parameters but the UI always passes `null` for all three — no input
    fields exist yet for the user to provide them. This is intentionally
    deferred; the plumbing is in place for Step 9 to fill in.
- `check_backend_connection` polls unconditionally every 10 seconds for the
  lifetime of the app window, including while a recording is in progress. This
  is intentional (spec section 9 wants the connection state visible at all
  times) and each request is a cheap, local, 3-second-timeout GET, but it is a
  background network call that happens regardless of user action — worth noting
  since section 7 says "the desktop app should send the finalized transcript
  only after the user clicks the button," which this respects (only `/health` is
  polled automatically, never `/analyze`), but it's the one automatic-by-design
  network behavior in the app and is called out here for transparency.
- Uvicorn's default `ConnectionResetError` traceback noise (from `--reload`-less
  short-lived health-check connections closing) appears in backend stderr during
  normal operation. Confirmed harmless — server keeps responding correctly — but
  not suppressed; a future pass could tune logging to hide it if it becomes
  distracting during backend development.
- No load/concurrency testing was performed — Phase 1 targets a single desktop
  client talking to a locally-run backend, so this wasn't in scope.

## Step 9 — Document upload + local RAG

**Status: Done (2026-08-14) — tested and manually verified by the user**

### Architecture decision: where does RAG live?

Investigated where to run document extraction/chunking/embedding/retrieval,
given the spec's constraint "keep RAG local... do not move the RAG engine into
FastAPI yet." Chose a **second local-only Python process** (`packages/rag`),
separate from `apps/backend` (the FastAPI analysis service), spawned/managed by
Tauri the same way the Step 4 PocketSphinx STT sidecar is managed
(`apps/desktop/src-tauri/src/rag/process.rs`, mirroring
`src/stt/sidecar.rs`) — except this one speaks plain HTTP bound to
`127.0.0.1:8100` rather than a stdin/stdout streaming protocol, since document
upload and search are naturally request/response operations. This keeps the
two backend concerns (interview analysis vs. knowledge-base RAG) in physically
separate processes with separate dependency trees (the RAG service pulls in
`torch`/`sentence-transformers`, which `apps/backend` has no reason to carry),
while still satisfying "local service/module, not in FastAPI."

### Embedding model and vector store selection (spec sections 11-12)

Researched local, non-LLM, ONNX/CPU-friendly embedding options and confirmed on
this machine:

- **Embedding model: `sentence-transformers/all-MiniLM-L6-v2`** — chosen for
  being the standard small/fast CPU sentence-embedding model (384 dimensions,
  ~90MB download, cached locally after first use). Verified: loads in ~35s
  cold (one-time), encodes in ~25ms for a couple of sentences. No API key, no
  GPU requirement, no LLM involved in generating embeddings (a dedicated
  `sentence-transformers` model, not a chat/completion model — satisfies "do
  NOT use the LLM to generate embeddings"). A true ONNX export would shave
  further latency but wasn't necessary to hit the interactive-use targets;
  documented in `app/embeddings.py` as a clean future swap via the
  `EmbeddingProvider` abstraction.
- **Vector store: SQLite + the `sqlite-vec` extension** — chosen over standing
  up Postgres/pgvector (spec: "do NOT introduce PostgreSQL yet unless there is
  a strong technical reason" — there wasn't one) or any cloud vector DB
  (explicitly excluded). `sqlite-vec` is a pure-C, dependency-free SQLite
  extension (Mozilla Builders project) providing a `vec0` virtual table with
  KNN search inside a single `.db` file, with prebuilt Windows wheels — no
  native build step. Verified working standalone (`vec_version()`, insert,
  KNN search) before building on top of it.

### What was implemented

**`packages/rag/app/` (Python, own venv — heavier deps than the STT sidecar or
the analysis backend):**

- `models.py` — `DocumentType` (7 values per spec section 9),
  `DocumentStatus` (8-state pipeline per spec section 19: Uploading →
  Extracting → Cleaning → Chunking → Embedding → Indexing → Ready, or Error),
  `DocumentMetadata`, `Chunk`, `SearchResult`, `compute_content_hash` (SHA-256
  for duplicate detection), extension/MIME validation constants.
- `loaders/` — `DocumentLoader` ABC plus `PdfLoader` (pypdf — no manual PDF
  parsing), `DocxLoader` (python-docx; extracts paragraphs, headings — tagged
  with `#` markers so the chunker treats DOCX and Markdown headings
  uniformly — and table cell text), `TxtLoader`/`MarkdownLoader` (UTF-8 with
  Latin-1 fallback). Each raises `ValueError` on corrupt/empty input rather
  than crashing the pipeline.
- `text_cleaning.py` — conservative whitespace/blank-line normalization plus a
  targeted PDF-line-wrap-artifact joiner; explicitly does **not** touch
  technical tokens like `C++`, `C#`, `.NET`, `AWS Lambda` (regression-tested).
- `chunking.py` — heading > paragraph > sentence > hard-cutoff boundary
  preference, ~650-token chunks (approximated via whitespace word count, no
  tokenizer dependency needed) with ~80-token overlap carried into the next
  chunk, both configurable via `CHUNK_SIZE_TOKENS`/`CHUNK_OVERLAP_TOKENS`.
- `embeddings.py` — `EmbeddingProvider` ABC, `LocalEmbeddingProvider`
  (sentence-transformers, lazy-loaded on first use).
- `vector_store.py` — `VectorStore` wrapping SQLite + `sqlite-vec`; documents
  and chunks tables plus a `vec0` virtual table for embeddings. Chunk ids are
  strings (UUID-derived) but `vec0` requires integer rowids, so a
  SHA-256-derived deterministic rowid is stored alongside each chunk row
  (`rowid_key` column) rather than kept only in an ephemeral in-process dict —
  this was caught and fixed during implementation so the rowid↔chunk_id
  mapping survives a process restart, not just the current process lifetime.
- `retriever.py` — `Retriever.search(query, top_k) -> (results, latency_ms)`.
  Semantic-only for Phase 1; kept as a narrow interface so hybrid
  search/reranking (spec section 14) can wrap or replace it later without
  changing callers.
- `pipeline.py` — `KnowledgeBaseService`, the orchestration entry point:
  validates file size/extension, computes content hash and skips reprocessing
  on an exact duplicate (spec section 8), runs
  extract→clean→chunk→embed→index while updating `DocumentStatus` at each
  stage, writes the raw file and extracted text to disk under the local
  AppData directory, and marks the document `ERROR` (with `error_message`, not
  a crash) on any pipeline failure.
- `routes.py` / `main.py` — FastAPI app: `/health`, `/documents/upload`,
  `/documents` (list), `/documents/{id}` (delete), `/knowledge-base/clear`,
  `/knowledge-base/status`, `/search`. Same CORS-allowlist and structured
  exception-handler pattern as `apps/backend`. Logging is metadata-only
  (`[UPLOAD] filename=... size=... type=...`, `[DOCUMENT] processed
  document_id=... chunks=...`) — extracted text/document content is never
  logged (spec section 18).

**`apps/desktop/src-tauri/src/rag/` (Rust):**

- `process.rs` — `RagServiceHandle::spawn()` locates the RAG service's own
  venv (`packages/rag/.venv/Scripts/python.exe`) and spawns
  `python -m uvicorn app.main:app --port 8100` as a child process. If the venv
  isn't found, returns `Ok(None)` rather than failing app startup — the rest
  of the app (recording, transcript, export, analyze) works normally even if
  the RAG environment was never set up. `wait_until_healthy_default()` polls
  `/health` for up to 60s (generous, to cover the embedding model's cold-start
  load time) before the app reports the service ready. `Drop` force-kills the
  child, same orphan-prevention pattern as `SttSidecar`.
- `client.rs` — `RagClient` (reqwest; `upload_document` uses
  `reqwest::multipart`, added alongside the `blocking` feature used by
  `process.rs`'s health-check poll).
- `types.rs` — wire types matching the RAG service's JSON shapes, with both
  `Serialize` and `Deserialize` (Tauri commands require `Serialize` on return
  types for IPC — this was a build error caught and fixed during
  implementation, not present in the earlier backend-integration work because
  those types only needed `Deserialize`).
- `commands.rs` — `check_rag_connection`, `upload_document`, `list_documents`,
  `delete_document`, `clear_knowledge_base`, `knowledge_base_status`,
  `search_knowledge_base`. Every command calls `ensure_rag_available()` first,
  which checks `AppState.rag_service` is `Some` and returns a clear
  "RAG service is not available..." error otherwise, rather than a raw
  connection-refused message.
- `lib.rs` — spawns the RAG service in a background thread from a Tauri
  `setup` hook (not blocking app launch), registers `tauri-plugin-fs` (needed
  for the frontend to read picked file bytes) and the new commands.

**`apps/desktop/src` (React/TS):**

- `types.ts` — `DocumentType`, `DocumentStatus`, `DocumentMetadata`,
  `KnowledgeBaseStatus`, `SearchResultItem`, `SearchResponse`.
- `Preparation.tsx` — the "Interview Preparation" panel (spec section 1):
  Role/Company text fields; a document-type selector + "Upload Document"
  button that opens a native file picker (`@tauri-apps/plugin-dialog`'s
  `open()`) filtered to PDF/DOCX/TXT/MD, reads the picked file's bytes
  (`@tauri-apps/plugin-fs`'s `readFile`), and invokes the `upload_document`
  command; a Knowledge Base dashboard showing document count, chunk count,
  overall status badge, and a per-document list with a status dot
  (color-coded by `DocumentStatus`), chunk count once ready, error message if
  failed, file size, and a Remove action; a "Clear Knowledge Base" action; and
  a Test Retrieval section (spec section 15) — a query input, "Search
  Knowledge Base" button, and results rendered as ranked
  `filename / score / text snippet` cards, plus the reported retrieval
  latency. Polls `check_rag_connection` + document/status lists every 5s so
  the dashboard stays current without manual refresh. Shows a clear fallback
  message (not a crash) if the RAG service isn't available.
- `App.tsx` — added a `Record`/`Prepare` tab bar; `role`/`company` state now
  lives in `App` (lifted out of `Preparation`) so `analyzeInterview` can pass
  them through to the `analyze_interview` command (spec section 16 — the
  request/response shape already had `role`/`company` fields from Step 8,
  previously always `null`; now populated from the Preparation tab's inputs
  when present). No LLM call, no RAG retrieval call, is wired into the analyze
  flow yet — per the explicit "DO NOT call an LLM yet... backend should
  continue returning mock analysis" constraint, `analyze_interview` still only
  talks to the Step 8 mock-analysis backend. Connecting retrieved knowledge-
  base context into that request body is left for Step 10, when a real
  LLM/RAG-context request architecture is decided (per spec section 16's own
  framing: "for now only verify retrieval/context generation").

### Automated tests (50 total, all passing)

`packages/rag/tests/`: `test_text_cleaning.py` (8 — including the
technical-token-preservation regression case), `test_chunking.py` (7 —
empty/short/long documents, heading boundaries, overlap carryover, oversized-
single-unit hard slicing, sequential indices), `test_loaders.py` (11 — PDF/
DOCX/TXT/Markdown happy paths including a *real* text-bearing PDF built via a
raw `pypdf` content stream rather than a placeholder blank page, corrupt-file
rejection for PDF/DOCX, empty-document rejection, unknown-extension
rejection), `test_vector_store.py` (7 — insert/list/find-by-hash/search/
delete/clear-all/counts, using deterministic fake embeddings), `test_pipeline.py`
(9 — end-to-end processing, duplicate-upload dedup, oversized-file rejection,
unsupported-extension rejection, corrupted-file → `ERROR` status with message,
empty-document rejection, delete, clear-all, status aggregation), `test_api.py`
(8 — HTTP-level upload/list/search/delete/clear/status, 422 on invalid
extension/empty-query/invalid-top_k). Run via `pytest` in ~1.5s (fake
embedding provider in `tests/conftest.py` avoids loading the real model for
tests that only need pipeline/API-level correctness, not retrieval quality).

Backend regression: `apps/backend`'s existing 12 tests re-run after all Step 9
work — still 12/12 passing, confirming Step 9 didn't touch or break Step 8.

### RAG quality testing (spec section 21 — real embedding model, not fakes)

Uploaded two realistic Markdown documents (a project write-up modeled on the
spec's own "RAG Security Copilot" example, and a matching resume) to the RAG
service running standalone with the real `all-MiniLM-L6-v2` model, then ran
the exact seven test queries from the spec:

| Query | Top result | Score | Relevant? |
|---|---|---|---|
| "Explain the RAG architecture I implemented." | Project: role/pipeline description | 0.484 | Yes |
| "What vector database did I use?" | Project: "...PostgreSQL... pgvector..." | 0.508 | Yes, exact match |
| "How did I handle false positives?" | Project: false-positives-handling paragraph | 0.482 | Yes, exact match |
| "What was my role in the Security Copilot project?" | Resume: "Led development of the Security Copilot..." | 0.551 (highest of all queries) | Yes, exact match |
| "What technologies did I use in the project?" | Project: role/pipeline description | 0.485 | Yes (adjacent chunk to the explicit tech-stack chunk, which also scored highly) |
| "How was the system deployed?" | Project: "...deployed on AWS using Docker... ECS..." | 0.487 | Yes, exact match |
| "What was the problem that RAG solved?" | Project: role/pipeline description | 0.459 | Reasonable (no chunk directly states "the problem," so the closest overview chunk winning is expected) |

Every query's top-ranked result was genuinely relevant, not just "an embedding
was generated" — this was checked by reading the actual returned chunk text
against each question, not inferred from scores alone. Retrieval latency:
9.8-14.1ms per query (well under the spec's 100ms target), measured via the
`/search` endpoint's reported `latency_ms` on this machine.

### Manual verification in the running desktop app (user-confirmed)

1. **Prepare tab renders correctly**: Role/Company fields, Upload Document
   section, Knowledge Base dashboard, Test Retrieval section all visible.
2. **Real document upload**: picked a real file via the native file dialog,
   uploaded it, and it appeared in the Knowledge Base list with a ready status
   dot and chunk count.
3. **Retrieval + delete + re-upload**: searched with a question related to the
   uploaded document and got relevant results with scores/filenames; removed
   the document via the Remove link and re-uploaded it without issue.
4. **No regression on the Record tab**: with Role/Company filled in, ran
   Start → Stop → Analyze Interview and confirmed the full Steps 1-8 flow
   (recording, transcript, timer, analyze) still works exactly as before.

### Privacy/data-flow verification

- The RAG service (`packages/rag`) has no HTTP client of its own — grep of the
  codebase confirms no `requests`/`httpx`/`urllib` outbound call exists
  anywhere in `packages/rag/app/`. It only ever receives calls *from* the
  desktop app on `127.0.0.1:8100` and never initiates a connection to anything
  else.
- `apps/backend` (the analysis service) never receives documents, file bytes,
  chunks, or embedding vectors — confirmed by reading `commands::analyze_interview`
  (unchanged from Step 8; it still only builds a transcript-only request) and
  by there being no code path anywhere that passes RAG-service data into the
  `backend::client` module.
- All knowledge-base state (raw files, extracted text, the SQLite+sqlite-vec
  database) lives under `%APPDATA%\WhitedotAI\knowledge\` — outside
  the repository, confirmed via `packages/rag/app/core/config.py`'s
  `_default_data_dir()` and the `.gitignore` entries added alongside this work.

### Known limitations

- **Document uploads via the desktop app were verified with one real file** in
  the manual pass, not the full definition-of-done checklist of resume + JD +
  project + prep-notes all uploaded together. The pipeline logic itself
  (loaders, chunking, dedup, error handling) is covered by the 50 automated
  tests across all four supported formats, and the RAG-quality test above
  covered multi-document retrieval (2 documents, cross-document ranking
  correctly favored the resume for the "my role" query) — but a full
  four-document-type upload session in the actual UI wasn't separately
  re-verified after the single-file manual test passed.
- **Hybrid search (semantic + keyword + metadata filtering + reranking)** is
  explicitly not implemented, per spec section 14 — the `Retriever` interface
  is narrow (`search(query, top_k)`) specifically so this can be added later
  without changing callers.
- **RAG context is not yet wired into the Analyze Interview request** — per
  the explicit Step 9 constraint not to call an LLM yet, `analyze_interview`
  still sends only transcript + role/company/job_description (job_description
  itself also still unpopulated — no JD-specific UI field exists yet beyond
  the generic document upload). Retrieval as a standalone, independently
  testable capability was the Step 9 deliverable; wiring it into the analysis
  request body is explicitly Step 10's concern.
- **RAG service process lifecycle**: like the Step 4 STT sidecar, an external
  `taskkill /F` on the parent `desktop.exe` (as opposed to a normal window
  close, which Tauri/the OS handles via the process tree) can orphan the RAG
  service child process, since Windows doesn't cascade-kill children. This was
  observed once during dev-loop iteration (documented the same way the Step 4
  STT sidecar orphaning was) and is mitigated for in-process exits by the
  `Drop` impl on `RagServiceHandle`, but an external force-kill of the whole
  app remains outside what any in-process Rust code can intercept.
- **No `WindowEvent::CloseRequested` handler** exists yet to explicitly stop
  either the STT sidecar, the RAG service, or in-progress recording when the
  user closes the app window — this gap was already noted in Step 6/7's
  progress notes and remains open; worth addressing in a dedicated pass rather
  than as a side effect of Step 9.
- The RAG service's own stdout/stderr are forwarded into the `log` crate
  (`rag::process::forward_child_output`) but this wasn't exercised/verified in
  this pass the way the STT sidecar's stderr forwarding was in Step 4 — noted
  as a minor follow-up, not a functional gap (the RAG service's HTTP responses
  and the desktop UI's error surfacing already provide the operationally
  important signal).

## Step 10 — Interview analysis with LLM

**Status: Core pipeline built and verified working; product direction changed
mid-verification (2026-08-14) — see Step 10b below.**

### What was built and verified

The full two-stage LLM analysis pipeline described in the original Step 10 spec
was implemented and is functionally working, end to end, with a real OpenAI key:

- **Backend** (`apps/backend/app/services/llm/`): `LLMProvider` abstraction
  (`OpenAIProvider` — real, implemented; `AnthropicProvider` — stub, raises
  `NotImplementedError`; `MockLLMProvider` — deterministic fallback),
  `get_llm_provider()` selection with safe fallback to mock on missing
  key/unrecognized provider. `app/services/prompt_builder.py`: hallucination-
  control system prompt + per-question and overall-aggregate user prompts.
  `app/services/analysis_service.py`: two-stage orchestration (Stage 1 per
  question -> `QuestionAnalysis`; Stage 2 aggregate -> `OverallInterviewAnalysis`),
  with per-question failure isolation (one bad LLM response doesn't lose the
  rest) and an SSE streaming endpoint (`POST /api/v1/interviews/analyze/stream`,
  via `sse-starlette`) alongside the original non-streaming endpoint.
  New schemas (`app/schemas/interview.py`: `QuestionAnswer`, `RetrievedChunk`;
  `app/schemas/analysis.py`: `QuestionAnalysis`, `OverallInterviewAnalysis`)
  with strict Pydantic validation, including hard per-chunk/per-field length
  caps. 50 backend tests (prompt builder, LLM provider selection/mocking,
  two-stage analysis scenarios including malformed-JSON/missing-field/
  provider-exception/partial-failure/truncation cases, plus the original 14
  interview-endpoint tests updated for the new schema) — all passing.
- **Desktop (Rust)**: `analyzer::extract_question_answers` — deterministic,
  local, no-LLM question/answer extraction from the finalized transcript
  (heading/source/timestamp/text-pattern heuristics only, per the "no LLM for
  basic segmentation" requirement), 10 unit tests. `rag::RetrievalPlanner` —
  per-question local RAG search with similarity-threshold filtering,
  deduplication, and context-size budgeting, 9 unit tests (including a
  regression test for a real bug found during manual testing — see below).
  `backend::client::BackendClient::analyze_stream` — SSE consumer with its own
  CRLF-safe frame parser, 7 unit tests (also added after a real bug — see
  below). All Rust changes together: 26 passing unit tests, `cargo check` clean.
- **Desktop (React)**: `ResultsDashboard.tsx` (Overview/Questions/Strengths/
  Weaknesses tabs, per-question cards with assessment/strengths/issues/
  improved-answer/expandable-sources, score bars, AI-disclaimer banner),
  streaming progress wired to `analysis:progress` Tauri events. `tsc --noEmit`
  clean.
- **`.env` auto-loading fixed**: `apps/backend/app/core/config.py` did not
  actually load `.env` (only read already-set process env vars) — found while
  wiring up the real OpenAI key for testing, fixed with `python-dotenv`'s
  `load_dotenv()` called before `Settings`' class-level `os.getenv()` reads.

### Two real bugs found and fixed during manual end-to-end testing

1. **SSE stream parser never matched CRLF line endings.** `sse-starlette`
   terminates SSE lines with `\r\n`, but `BackendClient::analyze_stream`'s
   frame-boundary search looked for a bare `"\n\n"`, which never matched —
   the entire response silently accumulated into the buffer and the function
   returned `"analysis stream ended without a final result"` even though the
   backend's response was completely correct (verified independently via
   `curl`, which showed a correct `event: complete` frame with the full
   result). Fixed by normalizing `\r\n` -> `\n` on the accumulated buffer
   (not per-chunk, since a `\r\n` pair can be split across two network
   chunks) before searching for frame boundaries. The parsing logic was
   extracted into a standalone `drain_sse_events` function specifically so it
   could be unit-tested without a live server; 7 tests added covering CRLF/LF
   frames, multi-frame chunks, partial trailing frames, unparseable-frame
   skipping, and full-result extraction.
2. **An oversized retrieved RAG chunk could exceed the backend's hard
   per-chunk validation limit.** `RetrievalPlanner`'s "always keep at least
   one result even if it exceeds the total context budget" fallback let a
   single chunk larger than the backend's `MAX_CHUNK_TEXT_LENGTH` (4000 chars)
   through untouched, causing a 422 validation error
   (`question_answers.0.retrieved_context.0.text: String should have at most
   4000 characters`) on a real interview with real uploaded documents. Fixed
   by truncating every chunk to a local `MAX_CHUNK_CHARS` (3900, under the
   backend's limit) before the total-budget accounting runs, using a
   UTF-8-char-boundary-safe truncation (not byte-slicing). Both the
   truncation logic and its char-boundary safety are unit tested.

Both bugs were caught specifically by manual testing against the real running
app with real audio and real documents — neither was caught by the (extensive)
automated test suites, because the suites tested each layer in isolation with
synthetic data that happened not to trigger either edge case. This is recorded
as a concrete argument for why the manual end-to-end pass mattered even though
the automated coverage was already large.

### Manual verification status when the product direction changed

Confirmed working via direct `curl` testing against the real backend with a
real OpenAI key: both the non-streaming and SSE-streaming analysis endpoints
produce genuinely high-quality, context-grounded output — the model correctly
cross-referenced candidate answers against retrieved RAG chunks, correctly
flagged an answer as unsupported when `retrieved_context` was empty rather
than inventing corroborating detail, and produced specific (non-generic)
scores/feedback. This confirms the hallucination-control prompt instructions
are functioning, not just present as text.

Confirmed working via the actual desktop UI, after both bugs above were fixed:
recording -> stop -> Analyze Interview -> streaming progress -> Results
Dashboard, including the "zero questions extracted" degrade-gracefully path
(shown correctly when a test transcript had no question-shaped text).

**Not completed**: a full manual pass with real, clearly-articulated
interview Q&A content reaching the Results Dashboard through the actual
running app (as opposed to via `curl`) — every UI attempt used improvised
test speech that PocketSphinx transcribed too poorly to contain any
question-shaped text for the (correctly-functioning) extraction heuristic to
find. This is what triggered the product-direction conversation below: rather
than keep fighting ad hoc test audio against a large post-interview dashboard,
the user redirected effort toward a tighter, faster-to-validate interaction
loop — see Step 10b.

## Step 10b — Interview Mode: minimal live overlay (in progress)

**Status: In progress, started 2026-08-14.**

### Why this pivot happened

Mid-way through Step 10's manual verification, the user determined that the
full post-interview analysis dashboard (Recording Complete screen, Questions/
Strengths/Weaknesses tabs, overall scoring) — while technically working
end-to-end — was not the product interaction they actually wanted to validate
first. The architecture underneath it (WASAPI capture, PocketSphinx, local
RAG, FastAPI, OpenAI integration) had already proven itself functionally
sound; what hadn't been validated was the *live, in-the-moment* interaction
loop: interviewer speaks -> question text appears -> user presses ENTER ->
answer appears, all in one small always-on-top overlay, with no page
navigation and no post-interview analysis step.

The existing Step 1-10 implementation is **not being deleted**. The full
dashboard, transcript export, document preparation, and multi-question
analysis pipeline remain in the codebase for later use; this milestone adds a
new, separate "Interview Mode" alongside them rather than replacing anything.

### Scope for this milestone (see spec sections 1-26 of the pivot instructions)

1. A frameless, transparent, always-on-top, draggable/resizable Tauri overlay
   window ("Interview Mode"), positioned bottom-right by default.
2. Windows `SetWindowDisplayAffinity(WDA_EXCLUDEFROMCAPTURE)` screen-capture
   exclusion, with the app honestly reporting whether it actually succeeded
   (never claiming protection if the API call failed) — tested against actual
   Windows capture/screen-share mechanisms, not assumed from CSS transparency.
3. The existing live PocketSphinx transcript feeding directly into the
   overlay's "Listening" state — still no automatic question detection; the
   user decides when to press ENTER.
4. STT tuning (end-of-speech stabilization window, audio buffering) aimed at
   more complete/stable partial-to-final text without materially increasing
   latency — configurable via `STT_END_SILENCE_MS`.
5. ENTER sends the current displayed question text (not the full transcript,
   not prior questions) through local RAG (`TOP_K=3`) -> a new, simple
   single-question backend endpoint -> a configurable low-cost OpenAI model,
   with a short, conversational, first-person, hallucination-controlled
   system prompt distinct from the full analysis prompt.
6. The answer streams into the same overlay (plain-text streaming is
   acceptable; no malformed/partial JSON ever rendered), with a Copy button,
   then the overlay returns to "Listening" for the next question.
7. A single settings affordance (gear icon) covering STT/overlay/LLM/knowledge-
   base/hotkey configuration — no other navigation exists in Interview Mode.

Work in progress — see subsequent progress entries for implementation detail,
manual test results (STT quality/latency before/after tuning, screen-capture
exclusion test results across available capture mechanisms, multi-question
cycle testing), and known limitations.

## Step 11 — Results dashboard

**Status: Core dashboard implemented as part of Step 10 (see above) — revisit
after Step 10b (Interview Mode) is validated, per explicit user direction.**

## Step 12 — Installer/packaging

**Status: Not started**

---

## Step 11 — STT engine replacement (PocketSphinx → NeMo FastConformer 80ms)

PocketSphinx was producing unusable transcripts on real speech. A side-by-side
capture of the same podcast audio showed it turning "retrieval augmented
generation" into "retrieval on reddit generation", "chunk your documents" into
"jog your documents", and "new series" into "new theories".

Ten engine configurations were benchmarked at 1x real time on identical audio
(`packages/stt-bench/`, results in `docs/stt-benchmark.md`). NeMo streaming
FastConformer EN 80ms int8 via sherpa-onnx was selected and is now in production.

**The larger finding was not about the engine.** Instrumenting the capture path
(`src/bin/audio_probe.rs`) showed WASAPI loopback delivers *no packets at all*
while the render endpoint is idle — not silent packets, nothing. Since every
speech endpointer finalizes on trailing silence, the final for a question never
fired until the interviewer happened to speak again. `audio::SilenceGapFiller`
reconstructs the missing time so the sidecar always sees a continuous timeline.
This accounted for the late finals, lost last words, and merged questions
independently of which recognizer was running.

The capture→gap-fill→STT loop moved out of `commands.rs` into
`audio::run_stt_pipeline`, free of Tauri types, so `src/bin/pipeline_test.rs`
exercises the shipping code headlessly rather than a copy of it.

Verified against live system audio: three questions transcribed verbatim with
zero word errors, finalization between 461-708ms, partials every 150-200ms that
only extend. Start → Pause → Resume → Stop confirmed with speech timestamped
against the pause window — audio spoken while paused does not reach the
transcript, and the pause flush commits the in-flight question rather than
losing it.

An earlier run appeared to show questions merging; that turned out to be a
podcast playing concurrently with the test speech, leaving no silence to
endpoint on. With real gaps, segmentation is clean. No change was made.

Full detail: `docs/stt-migration.md`.

---

## Step 12 — Interview Mode: chat overlay + conversation memory

The overlay showed one question and one answer at a time, replacing both on
every new question, and each ASK AI call was independent — so a follow-up like
"why did you choose that?" had nothing to resolve "that" against.

**UI.** Rebuilt as a small translucent floating chat window. The whole header
bar is the drag region; controls are down to a recording dot, − / + font size,
settings, and close, plus one ASK AI button on the compose row. Copy and Next
Question are gone — conversation text is selectable, and a new question just
appends rather than needing an explicit reset. The conversation scrolls and
auto-follows.

Opacity now tints the panel background (`--overlay-alpha`) instead of the
element. Applying `opacity` to the whole overlay faded the text with it, which
made a genuinely translucent window unreadable.

**Conversation memory.** `AskRequest` gained `conversation_history`, replayed
in `_build_messages` as real user/assistant turns between the system prompt and
the current question — not flattened into a text block, since a follow-up is
only resolvable if the model can see its own previous answer as an assistant
turn. Only bare Q/A text is replayed: retrieval context and the length/style
instructions stay on the current question, so stale context can't leak into a
new answer.

History is capped twice: the desktop forwards the last 6 turns (time-to-first
token is what the user feels mid-interview), and the schema rejects more than
20 as a backstop.

Verified against the live OpenAI provider with a controlled pair — the same
question "Why did you choose that?" answers generically with no history, and
resolves to "semantic search with sentence-transformer embeddings" with it.

---

## Step 13 — Speaker diarization: built, then fully rolled back

Speaker diarization for Meeting Mode (per-utterance "Speaker N" labels via
sherpa-onnx `SpeakerEmbeddingExtractor` embeddings + incremental clustering)
was implemented, iterated on extensively against real WASAPI-captured audio,
and ultimately **removed completely** at the user's explicit request. Real
multi-speaker accuracy could not be validated to the required bar within the
session, and the user chose to roll the feature all the way back rather than
continue tuning it.

**What was removed:**
- `packages/stt/streaming_asr_sidecar/diarization.py` and `diarization_v2.py`
  (the two clustering engines — simple nearest-neighbor and an
  evidence-accumulation/provisional-Unknown design).
- `packages/stt/scripts/install_speaker_model.py` and the downloaded
  `models/speaker-embedding/wespeaker_en_voxceleb_resnet34_LM.onnx` model file.
- `packages/stt/diarization_bench/` (benchmark/replay/metrics tooling built to
  validate diarization against real captured audio).
- `apps/desktop/src-tauri/src/bin/diarization_capture.rs` (WASAPI test-capture
  binary).
- All `speaker_id` / `utterance_id` / `speaker_correction` fields from the
  sidecar wire protocol, `SttEvent`, `SidecarLine`, and `TranscriptSegment`
  (Rust and the Python sidecar both reverted to the pre-diarization shape).
- `rename_speaker` / `get_speaker_names` Tauri commands and the
  `speaker_names: Mutex<HashMap<String, String>>` field on `AppState`.
- Speaker grouping, rename-inline-editing, and the "Identifying…" pending
  label from `MeetingRecorder.tsx` — Meeting Mode is now a plain live
  transcript with no speaker attribution, and its CSS (`.meeting-speaker-*`)
  was deleted along with the markup.
- `DIARIZATION_ENGINE` / `SPEAKER_MODEL_DIR` env vars (no longer read anywhere).
- The `speakerId` / `speakerNames` fields from JSON transcript export.

**What was explicitly kept, unmodified:** NeMo STT itself, WASAPI capture, the
periodic soft-flush finalize mechanism (added during diarization work to fix
utterances with no natural silence gap — this is a general STT-robustness fix
independent of diarization and stayed in `sidecar.py`'s worker loop), Interview
Mode, RAG, the LLM pipeline, and Custom Agents.

**Verification after rollback:**
- `cargo build` and `cargo test` in `apps/desktop/src-tauri`: build clean, all
  52 unit tests pass (2 pre-existing unrelated doctest failures in
  `rag/retrieval_planner.rs` and `interview_mode/commands.rs` — both are
  ASCII-arrow diagrams in doc comments misparsed as Rust code, present before
  this session and untouched by it).
- `npx tsc --noEmit -p .` in `apps/desktop`: no errors.
- `python -m py_compile streaming_asr_sidecar/sidecar.py`: clean; direct
  import confirms no `_build_diarizer`/`_is_speechlike`/diarization symbols
  remain.
- Ran the actual sidecar subprocess against a real captured WAV: `ready` event
  no longer advertises a `diarization` field, and no event in the stream
  carries `speaker_id` at any point.
- Repo-wide grep for `diarization|speaker_id|SpeakerUpdate|rename_speaker|
  speaker_names|SPEAKER_MODEL_DIR|DIARIZATION_ENGINE` across
  `apps/desktop/src`, `apps/desktop/src-tauri/src`, and `packages/stt` returns
  no matches other than a stale doc-comment (fixed) and the vendored
  `sherpa_onnx` package's own unrelated `SpeakerEmbeddingExtractor` API
  surface (not our code, left as-is).

STT, NeMo, WASAPI, the gap filler and the question buffer were not touched.
