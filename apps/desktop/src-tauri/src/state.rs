use std::sync::Mutex;
use std::thread::JoinHandle;

use crate::audio::{PauseSignal, StopSignal};
use crate::rag::RagServiceHandle;
use crate::transcript::{RecordingState, TranscriptManager};

/// One item tracked live during a Meeting session (a key point, decision, or
/// action item) — just the text; the list it lives in (`MeetingSessionState`)
/// carries the kind.
#[derive(Debug, Clone, Default, serde::Serialize)]
pub struct TrackedItem {
    pub text: String,
}

/// In-memory state for the currently-open Meeting session, tracked live from
/// the overlay. Reset by `clear_meeting_session` when a new meeting starts.
#[derive(Debug, Default)]
pub struct MeetingSessionState {
    pub key_points: Vec<TrackedItem>,
    pub decisions: Vec<TrackedItem>,
    pub action_items: Vec<TrackedItem>,
}

/// Handles for an in-progress recording session, held so Tauri commands can stop it
/// later. Wrapped in `Mutex` because Tauri commands run on arbitrary threads from
/// the async runtime.
pub struct CaptureSession {
    pub stop_signal: Option<StopSignal>,
    pub pause_signal: Option<PauseSignal>,
    pub system_audio_thread: Option<JoinHandle<()>>,
    pub mic_thread: Option<JoinHandle<()>>,
    pub pipeline_thread: Option<JoinHandle<()>>,
    pub recording_state: RecordingState,
}

impl Default for CaptureSession {
    fn default() -> Self {
        Self {
            stop_signal: None,
            pause_signal: None,
            system_audio_thread: None,
            mic_thread: None,
            pipeline_thread: None,
            recording_state: RecordingState::Idle,
        }
    }
}

#[derive(Default)]
pub struct AppState {
    pub capture: Mutex<CaptureSession>,
    pub transcript: Mutex<TranscriptManager>,
    /// `None` if the RAG service's venv wasn't found at startup (see
    /// `rag::process::RagServiceHandle::spawn`) — document upload/search
    /// commands report a clear "unavailable" error in that case rather than
    /// panicking.
    pub rag_service: Mutex<Option<RagServiceHandle>>,
    /// Live-tracked key points/decisions/action items for the currently open
    /// Meeting session. See `meeting_mode::commands`.
    pub meeting_session: Mutex<MeetingSessionState>,
    /// Mic-only capture session for Notes' voice dictation — reuses
    /// `CaptureSession` (system-audio fields simply stay `None`) so dictation
    /// gets the same start/pause/resume/stop lifecycle without a second
    /// struct. See `notes_mode::commands`.
    pub notes_dictation: Mutex<CaptureSession>,
}

// `AnalyticsQueue` is registered as its own top-level Tauri-managed state
// (see lib.rs's `.manage(analytics::AnalyticsQueue::default())`) rather than
// a field here, since it's `Mutex<Vec<_>>`-backed and needs to be reachable
// from a periodic background flush task independent of any `AppState` lock.
