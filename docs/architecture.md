# Architecture

## Overview

Interview Assistant is a Windows desktop application that captures system audio during
an interview, transcribes it locally with a streaming neural ASR model running on the
CPU (no cloud STT), and — only when the user explicitly requests it — sends the
finalized transcript to a FastAPI backend for RAG-augmented LLM analysis.

STT is NVIDIA NeMo streaming FastConformer (English, 80 ms chunk, int8) via
sherpa-onnx. It replaced CMU PocketSphinx after a benchmark of ten engine
configurations — see `docs/stt-benchmark.md` for the comparison and
`docs/stt-migration.md` for what shipped and the verification numbers.

```
                    WINDOWS EXE
                         |
             +-----------+-----------+
             |                       |
        WASAPI Audio             React UI
             |
             v
      SilenceGapFiller
             |
             v
     Streaming ASR sidecar
             |
             v
       Transcript
             |
             | User clicks "Analyze"
             v
        FastAPI Backend
             |
             v
            RAG
             |
             v
            LLM
             |
             v
     Interview Analysis
             |
             v
       Desktop UI
```

This is the target end-state pipeline. As of 2026-08-14, everything through
"FastAPI Backend" is built and verified (see `docs/progress.md` Steps 1-8); RAG and
a real LLM are not yet implemented — the backend currently returns a deterministic
mock analysis (`MockAnalysisProvider`) in place of the RAG/LLM stages.

## Hard boundary: local vs backend

- **Local (Rust, inside the Tauri process)**: WASAPI capture, audio buffering/resampling,
  streaming ASR decoding, transcript assembly, session storage, hotkeys, tray.
- **Backend (Python/FastAPI, separate process/service)**: receives only text (finalized
  transcript + optional role/company/job-description/candidate-context strings —
  document upload for RAG is not yet built), and (once implemented) will do RAG
  retrieval and call an LLM provider. Today it returns a mock analysis instead. It
  never receives raw audio and never controls Windows audio.

This boundary is enforced by construction: the Rust audio/STT code has no HTTP client
wired to send audio anywhere, and the only network call the desktop app makes with
audio-derived data is `POST /api/v1/interviews/analyze` (see "Desktop-side backend
integration" below) with a JSON transcript payload — built and running as of Step 8.

## Desktop stack

- **Tauri 2** shell — Rust backend process, WebView2-based window.
- **React + TypeScript + Vite** — UI (recording controls, transcript view, results
  dashboard, settings).
- **Rust crates** (as actually used — see `docs/progress.md` Steps 3-4 for why these
  were chosen over the originally-planned `cpal`/FFI-bindgen approach):
  - `wasapi` (HEnquist/wasapi-rs) for WASAPI loopback system-audio capture and
    microphone capture. `cpal` was evaluated and rejected — it has no built-in
    support for loopback capture of the default render/output device.
  - `rubato` (pinned to `0.15`, not the newer `5.x` which rewrote the API) for
    resampling captured audio to 16kHz mono ahead of STT.
  - STT runs **out of process**: a local Python sidecar
    (`packages/stt/streaming_asr_sidecar/sidecar.py`, using `sherpa-onnx` from
    its own venv at `packages/stt/.venv`) spoken to over stdin/stdout by
    `apps/desktop/src-tauri/src/stt/sidecar.rs`. Keeping inference in a child
    process is what guarantees a slow decode can never stall the Tauri UI
    thread. The previous PocketSphinx sidecar is still present and selectable
    via `STT_ENGINE=pocketsphinx` for A/B comparison without a rebuild.
  - sherpa-onnx also ships a C API and Rust bindings, so the engine could move
    in-process later and drop the Python dependency; the sidecar boundary was
    kept for now because it isolates the UI thread for free.
  - `tauri-plugin-dialog` for native Save-As dialogs (transcript export).
  - `tauri-plugin-global-shortcut` for hotkeys, `tauri` tray APIs for the system
    tray — not yet implemented (planned for a later step, see progress.md).

### Module layout (Rust, inside `apps/desktop/src-tauri/src`, as actually built)

```
audio/
  mod.rs          AudioChunk, AudioSource, StopSignal, PauseSignal, compute_rms
  device_manager.rs AudioDeviceManager (list_output_devices/list_input_devices)
  system_capture.rs SystemAudioCapture (WASAPI loopback capture thread)
  gap_fill.rs     SilenceGapFiller — reconstructs the audio timeline while the
                  render endpoint is idle and WASAPI delivers no packets at all.
                  Without it, endpointing never fires and finals hang.
  pipeline.rs     run_stt_pipeline — the capture->gap-fill->STT loop, free of
                  Tauri types so src/bin/pipeline_test.rs drives the real code
  metrics.rs      CaptureMetrics — pipeline counters used by src/bin/audio_probe.rs
  mic_capture.rs    MicrophoneCapture (WASAPI input capture thread; not yet wired
                    into any command — system audio is the Phase 1 primary source)
  resample.rs       AudioResampler wrapping rubato::FftFixedIn
stt/
  mod.rs          re-exports
  events.rs        SttEvent/SttEventKind, SidecarLine (sidecar JSON wire shape)
  sidecar.rs       SttSidecar — spawns/owns the STT Python child process,
                   a stdout reader thread, send_samples()/flush()/shutdown(),
                   Drop safety net
backend/
  mod.rs          re-exports
  config.rs        backend_url() (BACKEND_URL env var)
  types.rs         wire types matching apps/backend's Pydantic schemas
  client.rs        BackendClient — health_check(), analyze() against the
                   FastAPI analysis service (apps/backend)
rag/
  mod.rs          re-exports
  process.rs       RagServiceHandle::spawn()/shutdown(), wait_until_healthy* —
                   manages the local RAG service (packages/rag) child process
  types.rs         wire types matching the RAG service's JSON shapes
  client.rs        RagClient — health/upload/list/delete/clear/status/search
                   against the local RAG service (packages/rag)
transcript/
  mod.rs          TranscriptSegment, InterviewSession, RecordingState,
                   TranscriptManager (accumulates STT events into segments,
                   tracks pause/resume timing via elapsed_ms())
commands.rs       All Tauri IPC commands: device listing; start/pause/resume/stop
                  recording; get_recording_state; start_new_interview;
                  clear_transcript; export_transcript_txt/json;
                  check_backend_connection; analyze_interview;
                  check_rag_connection; upload_document; list_documents;
                  delete_document; clear_knowledge_base; knowledge_base_status;
                  search_knowledge_base
state.rs          AppState { capture: Mutex<CaptureSession>, transcript:
                  Mutex<TranscriptManager>, rag_service: Mutex<Option<RagServiceHandle>> }
lib.rs            Builder wiring: plugins (opener, dialog, fs), AppState, a
                  setup hook that spawns the RAG service in the background,
                  invoke_handler command list
```

Not yet implemented: `tray.rs`, `hotkeys.rs` (system tray and global shortcuts —
planned, see spec sections 20-21 and progress.md's remaining steps).

### Data flow while recording

```
System Audio (WASAPI loopback, system_capture.rs)
      -> resampled to 16kHz mono f32 (resample.rs)
      -> AudioChunk sent over a crossbeam channel to the pipeline thread
      -> pipeline thread (audio::run_stt_pipeline):
         - if paused: flush the sidecar once (committing the in-flight
           utterance), then drop chunks (still drained so the OS audio buffer
           never overflows). On resume, SilenceGapFiller::resync() discards the
           deficit accumulated across the pause.
         - if not paused, forward to:
             (a) SttSidecar::send_samples() -> Python child process stdin
             (b) the on_level callback -> Tauri event "audio:level"
         - SilenceGapFiller::take_silence() tops the stream up with synthesized
           silence whenever WASAPI delivered nothing. Loopback produces *no
           packets at all* on an idle endpoint, and endpointing needs trailing
           silence to fire — without this, finals hang until the next utterance.
      -> sidecar's stdout (JSON lines) read on a dedicated thread, parsed into
         SttEvent{Partial|Final}, forwarded to TranscriptManager.apply_event()
      -> TranscriptManager returns the changed TranscriptSegment, emitted as
         Tauri event "transcript:update" -> frontend renders it
```

Every recording state transition (`start_system_audio_capture`, `pause_recording`,
`resume_recording`, `stop_audio_capture`) also emits a `recording:state` Tauri
event carrying the new `RecordingState` (`Idle | Recording | Paused | Stopped`), so
the frontend's UI state machine stays in sync with the Rust side rather than
inferring state from command success/failure alone.

No component analyzes whether a given segment is a "question," and no component
decides when to call an LLM — this pipeline only ever produces timestamped text.
Segments are stored with `source: SYSTEM_AUDIO | MICROPHONE`, timestamps
(including STT-reported utterance `start_time`/`end_time`, process-relative), and
partial/final text only.

### Pause/resume semantics

Pausing does **not** stop WASAPI capture or the STT sidecar process — it
only gates the pipeline thread's forwarding of audio to STT and level events to the
UI (`audio::PauseSignal`, a plain atomic bool). This was a deliberate choice: it
keeps the sidecar's decoder state and the transcript-so-far completely untouched
across a pause (no utterance is force-finalized just because the user paused), and
makes resume instant (no process respawn). `InterviewSession::elapsed_ms()`
computes wall-clock-time-minus-accumulated-pause-time and freezes at the pause
timestamp while `Paused`, which is what the frontend timer mirrors client-side.

### Transcript export

`export_transcript_txt` / `export_transcript_json` (in `commands.rs`) open a native
Save-As dialog via `tauri-plugin-dialog`'s blocking API and write the file directly
from Rust (`std::fs::File::create`) — the export path has no network client and
never touches the (not-yet-built) backend. Both are reachable only from the
post-stop "Recording Complete" summary screen, never automatically.

## Backend

```
Desktop (Rust, backend/client.rs)
      |
      | HTTP (reqwest, JSON) — only after the user clicks "Analyze Interview"
      v
FastAPI (apps/backend/app/main.py)
      |
      v
Analysis Service (app/services/analysis_service.py)
      |
      v
MockAnalysisProvider (Phase 1 — the only implementation wired up)
```

**STT remains entirely local and does not run in the backend.** The backend
process never captures audio, never runs the ASR model, and never receives raw
audio — only the already-finalized transcript text (plus optional role/company/
job-description/candidate-context strings), and only after the user explicitly
clicks "Analyze Interview" on the post-stop summary screen. No automatic call
happens when recording stops.

- **FastAPI** app in `apps/backend/app`, structure:
  `api/routes/{health,interviews}.py` (thin route handlers) →
  `services/{interview_service,analysis_service}.py` (business logic) →
  `schemas/{interview,analysis,error}.py` (Pydantic v2 request/response contracts)
  → `core/config.py` (env-driven settings).
- `GET /health` → `{"status": "ok", "service": "interview-assistant-backend"}`.
- `POST /api/v1/interviews/analyze` — versioned from the start (`/api/v1/`) so the
  contract can evolve without breaking older desktop builds. Accepts
  `{ session_id, role?, company?, job_description?, candidate_context?, transcript:
  { duration_seconds, segments: [{ timestamp, source, text }] } }`. `source` is a
  strict enum (`SYSTEM_AUDIO` | `MICROPHONE`) — unknown values are rejected with
  422, not silently accepted.
- **Phase 1 returns a deterministic mock analysis only** — `AnalysisService` wraps
  an `AnalysisProvider` interface (`MockAnalysisProvider` is the only
  implementation; a future `LLMAnalysisProvider` slots in later without touching
  the route handler). Every score is `0`, every list (`strengths`/`improvements`/
  `questions`) is empty, and `message` explicitly states real LLM analysis isn't
  connected yet. A regression test (`test_response_never_reflects_fabricated_scores`)
  guards against this silently changing to look like real AI output.
- CORS is an explicit allowlist (`CORS_ALLOW_ORIGINS` env var, default covers the
  Tauri dev server and packaged-app WebView origins) — never `"*"`, including in
  future production configuration.
- Errors follow a consistent shape everywhere: `{ "error": { "code", "message" } }`,
  via a `RequestValidationError` handler (422) and a catch-all exception handler
  (500) in `main.py`.
- Logging is structured and metadata-only: `[API]`, `[INTERVIEW]`,
  `[TRANSCRIPT]`, `[ANALYSIS]` prefixed lines carry session id, segment count, and
  duration — never the transcript text itself, resumes, or any secret/API key.
- LLM access is planned to go through an `LLMProvider` abstraction
  (`OpenAIProvider`, `AnthropicProvider`, `MockLLMProvider`), selected via
  `LLM_PROVIDER` env var — **not yet built**; Phase 1's `AnalysisService` only
  has `MockAnalysisProvider` today. No key is ever hard-coded or sent to the
  frontend.
- Document upload (`POST /documents/upload`) and the RAG/vector-store pipeline
  described in earlier drafts of this document are **not yet implemented** — that
  is Step 9, tracked in `docs/progress.md`.

### Desktop-side backend integration (`apps/desktop/src-tauri/src/backend/`)

- `config.rs::backend_url()` reads `BACKEND_URL`, defaulting to
  `http://127.0.0.1:8000` — never a hard-coded production URL.
- `client.rs::BackendClient` wraps `reqwest` (no TLS backend enabled — Phase 1
  only ever talks plain HTTP to localhost, so pulling in rustls/native-tls would
  be unused weight; the `blocking` and `multipart` features were added in Step 9
  for the RAG service's health-check poll and file upload, shared by the same
  `reqwest` dependency). `health_check()` backs the UI's connection-status
  indicator; `analyze()` posts the transcript and parses either the
  `AnalysisResponse` or the structured `{error:{code,message}}` shape.
- `commands.rs::check_backend_connection` — liveness probe only, called by the
  frontend on a 10-second interval plus once on mount, to drive a
  `Backend: Connected | Offline | Connecting…` indicator in the UI. Never touches
  the transcript.
- `commands.rs::analyze_interview` — builds the wire request from the current
  `TranscriptManager` session, using **only finalized segments**
  (`segment.final_text`, never `partial_text`) converted to the backend's
  `MM:SS`/`HH:MM:SS` relative-timestamp string format. Rejects with an error
  before making any HTTP call if the transcript is empty. This is the only
  function in the entire desktop codebase that sends interview-derived data over
  the network, and it only runs when the user clicks "Analyze Interview."

## Local RAG (document upload + knowledge base)

```
User documents (resume, JD, project docs, notes)
      |
      v
Local RAG service (packages/rag, its own Python/FastAPI process,
                    127.0.0.1:8100 only — spawned/managed by Tauri,
                    NOT part of apps/backend)
      |
      v
Extraction (pypdf/python-docx/text) -> Cleaning -> Chunking
      |
      v
Embedding (sentence-transformers/all-MiniLM-L6-v2, local, CPU, no LLM)
      |
      v
Vector store (SQLite + sqlite-vec, one .db file under
              %APPDATA%\InterviewAssistant\knowledge\)
      |
      v
Retriever.search(query, top_k) -> ranked chunks
```

This is a second, separate local-only Python process from `apps/backend` —
deliberately kept out of the network-facing analysis backend per the Step 9
requirement to not move RAG into FastAPI yet. It is managed by Tauri as a
child process the same way the STT sidecar is
(`apps/desktop/src-tauri/src/rag/`, mirroring `src/stt/`), except it speaks
plain request/response HTTP rather than a stdin/stdout streaming protocol,
since document upload and search are naturally request/response operations.

**Nothing here uploads anywhere.** The RAG service has no outbound HTTP
client of its own — it only ever receives calls from the desktop app on
`127.0.0.1:8100`. `apps/backend` never receives documents, file bytes, chunks,
or embedding vectors; `commands::analyze_interview` (Step 8) is unchanged by
Step 9 and still only sends transcript text plus optional role/company/
job_description strings. Connecting retrieved knowledge-base context into the
analysis request is deferred to Step 10, once a real LLM/RAG-context request
architecture is decided.

- **Embedding model**: `sentence-transformers/all-MiniLM-L6-v2` — small
  (~90MB), fast on CPU (~25ms to encode a couple of sentences on this
  machine), no API key, no GPU required. Chosen over an ONNX export for Phase
  1 simplicity; swapping providers later only requires a new
  `EmbeddingProvider` implementation (`packages/rag/app/embeddings.py`), no
  change to chunking/vector-store/retriever code.
- **Vector store**: SQLite + the `sqlite-vec` extension — a single `.db` file,
  no server process, no cloud vector DB. Chosen specifically because a desktop
  app should not require the user to run a database server to search their
  own documents (`packages/rag/app/vector_store.py`).
- **Chunking**: heading > paragraph > sentence > hard-cutoff boundary
  preference, ~650-token chunks with ~80-token overlap
  (`packages/rag/app/chunking.py`).
- **Document/knowledge-base state** lives entirely under
  `%APPDATA%\InterviewAssistant\knowledge\` — raw files, extracted text, and
  the vector store — never inside the repository, never uploaded anywhere.
- Retrieval quality (not just plumbing) was manually verified with the real
  embedding model against realistic resume/project documents and the spec's
  own set of test interview questions — see `docs/progress.md` Step 9 for the
  exact queries, retrieved chunks, and scores. Retrieval latency measured at
  9.8-14.1ms per query, well under the 100ms target.

### Desktop-side RAG integration (`apps/desktop/src-tauri/src/rag/`)

- `process.rs::RagServiceHandle::spawn()` — locates the RAG service's own
  virtualenv (`packages/rag/.venv`, kept separate from the STT sidecar and the
  analysis backend's venvs since it carries much heavier dependencies —
  `torch`, `sentence-transformers`) and spawns
  `python -m uvicorn app.main:app --port 8100`. Returns `Ok(None)` rather than
  an error if the venv isn't set up, so the rest of the app (recording,
  transcript, export, analyze) keeps working normally without the RAG
  features available. `Drop` force-kills the child as an orphan-prevention
  safety net, the same pattern used for the STT sidecar (see Step 4 in
  `docs/progress.md` for why this matters on Windows).
- `client.rs::RagClient` — health check, document upload (multipart), list/
  delete documents, clear knowledge base, status, and search — all against
  `http://127.0.0.1:8100`.
- `commands.rs` — every RAG-related Tauri command
  (`check_rag_connection`/`upload_document`/`list_documents`/
  `delete_document`/`clear_knowledge_base`/`knowledge_base_status`/
  `search_knowledge_base`) checks the service is available first and returns
  a clear "RAG service is not available..." error otherwise, rather than a
  raw connection-refused message.
- The service is spawned from a Tauri `setup` hook on a background thread, so
  app launch is never blocked waiting for it (including the embedding model's
  cold-start load time).

## Explicit non-goals for Phase 1

No auth, billing, plans, multi-tenancy, enterprise admin, SSO, browser extensions,
platform-specific integrations (Zoom/Teams/Meet APIs), automatic question detection,
or automatic LLM invocation during recording. See `docs/progress.md` for current
status against the Phase 1 definition of done.

## Environment (inspected 2026-08-14)

| Tool | Version | Notes |
|---|---|---|
| OS | Windows 11 Home Single Language, build 26200 | |
| Node | v24.12.0 | |
| npm | 11.6.2 | |
| Rust | 1.97.1 (stable-x86_64-pc-windows-msvc) | correct toolchain for Tauri on Windows |
| Cargo | 1.97.1 | |
| Python | 3.12.10 (via `py -3`, not `python`) | plain `python`/`python3` alias to Microsoft Store stub — use `py -3` |
| VS Build Tools | 2022, C++ workload present (`Microsoft.VisualStudio.Component.VC.Tools.x86.x64`) | required for MSVC Rust linking + PocketSphinx native build |
| CMake | present (`C:\Program Files\CMake\bin\cmake.exe`) | needed to build PocketSphinx from source if no prebuilt binary used |
| Git | present | |
| Tauri CLI | not installed yet | will be added as a dev dependency (`@tauri-apps/cli`) |
| PocketSphinx | not installed (no system lib, no Python package) | must be built/vendored — see progress.md for chosen approach |

Risk flagged (2026-08-14) and since resolved: there is no maintained, actively-
published `pocketsphinx` Rust crate on crates.io equivalent to the Python bindings.
Resolved by using a local Python sidecar process (option (b) below) — decision and
verification recorded in `docs/progress.md` Step 4. Kept here for history:
(a) FFI bindgen against a vendored/built `libpocketsphinx`/`libsphinxbase` — rejected
as too fragile/time-consuming for Phase 1; (b) a thin sidecar process using the
`pocketsphinx` Python package via IPC — **chosen**.
