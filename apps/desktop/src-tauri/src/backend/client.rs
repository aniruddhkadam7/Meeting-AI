use std::time::Duration;

use futures_util::StreamExt;

use super::config::backend_url;
use super::types::{
    AgentAskRequest, AnalysisProgressEvent, AskRequest, AskResponse, ConsultingAskRequest,
    ConsultingAskResponse, ConsultingNote, ConsultingSummaryRequest, ErrorResponse,
    InterviewAnalysisRequest, MeetingAskRequest, MeetingSummary,
    MeetingSummaryRequest, NoteSummary, NotesAskRequest, NotesAskResponse, NotesSummaryRequest,
    OverallInterviewAnalysis, SalesAskRequest, SalesAskResponse, SalesCallSummary,
    SalesSummaryRequest, SetupAnalysisRequest, SetupAnalysisResponse,
};

pub struct BackendClient {
    http: reqwest::Client,
    base_url: String,
}

impl BackendClient {
    pub fn new() -> Self {
        crate::tls_init::ensure_installed();
        Self {
            http: reqwest::Client::builder()
                .timeout(Duration::from_secs(30))
                .build()
                .unwrap_or_default(),
            base_url: backend_url(),
        }
    }

    /// Used for the UI's connection-status indicator. Short timeout since this is
    /// meant to be a quick liveness probe, not the actual analysis call.
    pub async fn health_check(&self) -> Result<(), String> {
        let url = format!("{}/health", self.base_url);
        let response = self
            .http
            .get(&url)
            .timeout(Duration::from_secs(3))
            .send()
            .await
            .map_err(|e| format!("backend unreachable: {e}"))?;

        if response.status().is_success() {
            Ok(())
        } else {
            Err(format!("backend health check returned {}", response.status()))
        }
    }

    /// Non-streaming analysis call — kept for completeness/tests. The desktop
    /// UI uses `analyze_stream` so the user sees progress during what can be
    /// a multi-question, multi-LLM-call analysis.
    pub async fn analyze(&self, request: &InterviewAnalysisRequest) -> Result<OverallInterviewAnalysis, String> {
        let url = format!("{}/api/v1/interviews/analyze", self.base_url);
        let response = self
            .http
            .post(&url)
            .timeout(Duration::from_secs(300))
            .json(request)
            .send()
            .await
            .map_err(|e| format!("failed to reach backend: {e}"))?;

        let status = response.status();
        if status.is_success() {
            response
                .json::<OverallInterviewAnalysis>()
                .await
                .map_err(|e| format!("backend returned an unexpected response: {e}"))
        } else {
            let body_text = response.text().await.unwrap_or_default();
            if let Ok(err) = serde_json::from_str::<ErrorResponse>(&body_text) {
                Err(format!("{} ({})", err.error.message, err.error.code))
            } else {
                Err(format!("backend returned {status}: {body_text}"))
            }
        }
    }

    /// Streams analysis progress via Server-Sent Events, invoking `on_event`
    /// for each parsed progress event as it arrives. The event whose
    /// `stage == "complete"` carries the final validated
    /// `OverallInterviewAnalysis` in its `result` field — this function
    /// returns that once the stream ends. No event before that one ever
    /// contains unvalidated/partial JSON; the backend only emits fully
    /// Pydantic-validated fragments (see
    /// apps/backend/app/services/analysis_service.py).
    pub async fn analyze_stream<F>(
        &self,
        request: &InterviewAnalysisRequest,
        mut on_event: F,
    ) -> Result<OverallInterviewAnalysis, String>
    where
        F: FnMut(&AnalysisProgressEvent),
    {
        let url = format!("{}/api/v1/interviews/analyze/stream", self.base_url);
        let response = self
            .http
            .post(&url)
            .timeout(Duration::from_secs(600))
            .json(request)
            .send()
            .await
            .map_err(|e| format!("failed to reach backend: {e}"))?;

        if !response.status().is_success() {
            let status = response.status();
            let body_text = response.text().await.unwrap_or_default();
            if let Ok(err) = serde_json::from_str::<ErrorResponse>(&body_text) {
                return Err(format!("{} ({})", err.error.message, err.error.code));
            }
            return Err(format!("backend returned {status}: {body_text}"));
        }

        let mut stream = response.bytes_stream();
        let mut buffer = String::new();
        let mut final_result: Option<OverallInterviewAnalysis> = None;

        while let Some(chunk) = stream.next().await {
            let chunk = chunk.map_err(|e| format!("stream read error: {e}"))?;
            buffer.push_str(&String::from_utf8_lossy(&chunk));

            for event in drain_sse_events(&mut buffer) {
                if event.stage == "complete" {
                    if let Some(result) = event.result.clone() {
                        final_result = Some(result);
                    }
                }
                on_event(&event);
            }
        }

        final_result.ok_or_else(|| "analysis stream ended without a final result".to_string())
    }

    /// Interview Mode's single-question flow (non-streaming). Only ever
    /// called after the user presses ENTER on the currently displayed
    /// question — never automatically.
    pub async fn ask(&self, request: &AskRequest) -> Result<AskResponse, String> {
        let url = format!("{}/api/v1/ask", self.base_url);
        let response = self
            .http
            .post(&url)
            .timeout(Duration::from_secs(60))
            .json(request)
            .send()
            .await
            .map_err(|e| format!("failed to reach backend: {e}"))?;

        let status = response.status();
        if status.is_success() {
            response
                .json::<AskResponse>()
                .await
                .map_err(|e| format!("backend returned an unexpected response: {e}"))
        } else {
            let body_text = response.text().await.unwrap_or_default();
            if let Ok(err) = serde_json::from_str::<ErrorResponse>(&body_text) {
                Err(format!("{} ({})", err.error.message, err.error.code))
            } else {
                Err(format!("backend returned {status}: {body_text}"))
            }
        }
    }

    /// Interview Mode's single-question flow, streaming the answer text
    /// incrementally via `on_delta` (spec: plain-text streaming is
    /// acceptable — no structured JSON is streamed here, just raw answer
    /// text chunks). Returns the full concatenated answer once the stream
    /// completes.
    pub async fn ask_stream<F>(&self, request: &AskRequest, mut on_delta: F) -> Result<String, String>
    where
        F: FnMut(&str),
    {
        let url = format!("{}/api/v1/ask/stream", self.base_url);
        let response = self
            .http
            .post(&url)
            .timeout(Duration::from_secs(60))
            .json(request)
            .send()
            .await
            .map_err(|e| format!("failed to reach backend: {e}"))?;

        if !response.status().is_success() {
            let status = response.status();
            let body_text = response.text().await.unwrap_or_default();
            if let Ok(err) = serde_json::from_str::<ErrorResponse>(&body_text) {
                return Err(format!("{} ({})", err.error.message, err.error.code));
            }
            return Err(format!("backend returned {status}: {body_text}"));
        }

        let mut stream = response.bytes_stream();
        let mut buffer = String::new();
        let mut full_answer = String::new();

        while let Some(chunk) = stream.next().await {
            let chunk = chunk.map_err(|e| format!("stream read error: {e}"))?;
            buffer.push_str(&String::from_utf8_lossy(&chunk));

            for (event_name, data) in drain_raw_sse_frames(&mut buffer) {
                if event_name.as_deref() == Some("delta") && !data.is_empty() {
                    full_answer.push_str(&data);
                    on_delta(&data);
                }
            }
        }

        Ok(full_answer)
    }

    /// New Interview setup page's auto-analysis call: summarizes whatever
    /// resume/job-description text is available into a short "Interview
    /// Focus" the setup page can display. Called in the background while the
    /// user is still on the setup page — never blocks Start Interview.
    pub async fn analyze_setup(&self, request: &SetupAnalysisRequest) -> Result<SetupAnalysisResponse, String> {
        let url = format!("{}/api/v1/setup/analyze", self.base_url);
        let response = self
            .http
            .post(&url)
            .timeout(Duration::from_secs(20))
            .json(request)
            .send()
            .await
            .map_err(|e| format!("failed to reach backend: {e}"))?;

        let status = response.status();
        if status.is_success() {
            response
                .json::<SetupAnalysisResponse>()
                .await
                .map_err(|e| format!("backend returned an unexpected response: {e}"))
        } else {
            let body_text = response.text().await.unwrap_or_default();
            if let Ok(err) = serde_json::from_str::<ErrorResponse>(&body_text) {
                Err(format!("{} ({})", err.error.message, err.error.code))
            } else {
                Err(format!("backend returned {status}: {body_text}"))
            }
        }
    }

    /// Sales Mode's live single-question flow, streaming the suggestion text
    /// incrementally via `on_delta`. Mirrors `ask_stream` above.
    pub async fn sales_ask_stream<F>(&self, request: &SalesAskRequest, mut on_delta: F) -> Result<String, String>
    where
        F: FnMut(&str),
    {
        let url = format!("{}/api/v1/sales/ask/stream", self.base_url);
        let response = self
            .http
            .post(&url)
            .timeout(Duration::from_secs(60))
            .json(request)
            .send()
            .await
            .map_err(|e| format!("failed to reach backend: {e}"))?;

        if !response.status().is_success() {
            let status = response.status();
            let body_text = response.text().await.unwrap_or_default();
            if let Ok(err) = serde_json::from_str::<ErrorResponse>(&body_text) {
                return Err(format!("{} ({})", err.error.message, err.error.code));
            }
            return Err(format!("backend returned {status}: {body_text}"));
        }

        let mut stream = response.bytes_stream();
        let mut buffer = String::new();
        let mut full_answer = String::new();

        while let Some(chunk) = stream.next().await {
            let chunk = chunk.map_err(|e| format!("stream read error: {e}"))?;
            buffer.push_str(&String::from_utf8_lossy(&chunk));

            for (event_name, data) in drain_raw_sse_frames(&mut buffer) {
                if event_name.as_deref() == Some("delta") && !data.is_empty() {
                    full_answer.push_str(&data);
                    on_delta(&data);
                }
            }
        }

        Ok(full_answer)
    }

    /// Custom Agents' live single-question flow — the one generic ask
    /// endpoint shared by every predefined role and every fully custom
    /// agent. Mirrors `sales_ask_stream` above exactly (same SSE frame
    /// parser, same delta/full-answer accumulation).
    pub async fn agent_ask_stream<F>(&self, request: &AgentAskRequest, mut on_delta: F) -> Result<String, String>
    where
        F: FnMut(&str),
    {
        let url = format!("{}/api/v1/agents/ask/stream", self.base_url);
        let response = self
            .http
            .post(&url)
            .timeout(Duration::from_secs(60))
            .json(request)
            .send()
            .await
            .map_err(|e| format!("failed to reach backend: {e}"))?;

        if !response.status().is_success() {
            let status = response.status();
            let body_text = response.text().await.unwrap_or_default();
            if let Ok(err) = serde_json::from_str::<ErrorResponse>(&body_text) {
                return Err(format!("{} ({})", err.error.message, err.error.code));
            }
            return Err(format!("backend returned {status}: {body_text}"));
        }

        let mut stream = response.bytes_stream();
        let mut buffer = String::new();
        let mut full_answer = String::new();

        while let Some(chunk) = stream.next().await {
            let chunk = chunk.map_err(|e| format!("stream read error: {e}"))?;
            buffer.push_str(&String::from_utf8_lossy(&chunk));

            for (event_name, data) in drain_raw_sse_frames(&mut buffer) {
                if event_name.as_deref() == Some("delta") && !data.is_empty() {
                    full_answer.push_str(&data);
                    on_delta(&data);
                }
            }
        }

        Ok(full_answer)
    }

    pub async fn sales_summarize(&self, request: &SalesSummaryRequest) -> Result<SalesCallSummary, String> {
        let url = format!("{}/api/v1/sales/summarize", self.base_url);
        let response = self
            .http
            .post(&url)
            .timeout(Duration::from_secs(60))
            .json(request)
            .send()
            .await
            .map_err(|e| format!("failed to reach backend: {e}"))?;

        let status = response.status();
        if status.is_success() {
            response
                .json::<SalesCallSummary>()
                .await
                .map_err(|e| format!("backend returned an unexpected response: {e}"))
        } else {
            let body_text = response.text().await.unwrap_or_default();
            if let Ok(err) = serde_json::from_str::<ErrorResponse>(&body_text) {
                Err(format!("{} ({})", err.error.message, err.error.code))
            } else {
                Err(format!("backend returned {status}: {body_text}"))
            }
        }
    }

    /// Meeting Mode's live single-question flow, streaming the answer text
    /// incrementally via `on_delta`. Mirrors `sales_ask_stream` above.
    pub async fn meeting_ask_stream<F>(&self, request: &MeetingAskRequest, mut on_delta: F) -> Result<String, String>
    where
        F: FnMut(&str),
    {
        let url = format!("{}/api/v1/meeting/ask/stream", self.base_url);
        let response = self
            .http
            .post(&url)
            .timeout(Duration::from_secs(60))
            .json(request)
            .send()
            .await
            .map_err(|e| format!("failed to reach backend: {e}"))?;

        if !response.status().is_success() {
            let status = response.status();
            let body_text = response.text().await.unwrap_or_default();
            if let Ok(err) = serde_json::from_str::<ErrorResponse>(&body_text) {
                return Err(format!("{} ({})", err.error.message, err.error.code));
            }
            return Err(format!("backend returned {status}: {body_text}"));
        }

        let mut stream = response.bytes_stream();
        let mut buffer = String::new();
        let mut full_answer = String::new();

        while let Some(chunk) = stream.next().await {
            let chunk = chunk.map_err(|e| format!("stream read error: {e}"))?;
            buffer.push_str(&String::from_utf8_lossy(&chunk));

            for (event_name, data) in drain_raw_sse_frames(&mut buffer) {
                if event_name.as_deref() == Some("delta") && !data.is_empty() {
                    full_answer.push_str(&data);
                    on_delta(&data);
                }
            }
        }

        Ok(full_answer)
    }

    pub async fn meeting_summarize(&self, request: &MeetingSummaryRequest) -> Result<MeetingSummary, String> {
        let url = format!("{}/api/v1/meeting/summarize", self.base_url);
        let response = self
            .http
            .post(&url)
            .timeout(Duration::from_secs(60))
            .json(request)
            .send()
            .await
            .map_err(|e| format!("failed to reach backend: {e}"))?;

        let status = response.status();
        if status.is_success() {
            response
                .json::<MeetingSummary>()
                .await
                .map_err(|e| format!("backend returned an unexpected response: {e}"))
        } else {
            let body_text = response.text().await.unwrap_or_default();
            if let Ok(err) = serde_json::from_str::<ErrorResponse>(&body_text) {
                Err(format!("{} ({})", err.error.message, err.error.code))
            } else {
                Err(format!("backend returned {status}: {body_text}"))
            }
        }
    }

    /// Consulting Mode's live single-question flow, streaming the guidance
    /// text incrementally via `on_delta`. Mirrors `ask_stream` above.
    pub async fn consulting_ask_stream<F>(
        &self,
        request: &ConsultingAskRequest,
        mut on_delta: F,
    ) -> Result<String, String>
    where
        F: FnMut(&str),
    {
        let url = format!("{}/api/v1/consulting/ask/stream", self.base_url);
        let response = self
            .http
            .post(&url)
            .timeout(Duration::from_secs(60))
            .json(request)
            .send()
            .await
            .map_err(|e| format!("failed to reach backend: {e}"))?;

        if !response.status().is_success() {
            let status = response.status();
            let body_text = response.text().await.unwrap_or_default();
            if let Ok(err) = serde_json::from_str::<ErrorResponse>(&body_text) {
                return Err(format!("{} ({})", err.error.message, err.error.code));
            }
            return Err(format!("backend returned {status}: {body_text}"));
        }

        let mut stream = response.bytes_stream();
        let mut buffer = String::new();
        let mut full_answer = String::new();

        while let Some(chunk) = stream.next().await {
            let chunk = chunk.map_err(|e| format!("stream read error: {e}"))?;
            buffer.push_str(&String::from_utf8_lossy(&chunk));

            for (event_name, data) in drain_raw_sse_frames(&mut buffer) {
                if event_name.as_deref() == Some("delta") && !data.is_empty() {
                    full_answer.push_str(&data);
                    on_delta(&data);
                }
            }
        }

        Ok(full_answer)
    }

    pub async fn consulting_summarize(
        &self,
        request: &ConsultingSummaryRequest,
    ) -> Result<ConsultingNote, String> {
        let url = format!("{}/api/v1/consulting/summarize", self.base_url);
        let response = self
            .http
            .post(&url)
            .timeout(Duration::from_secs(60))
            .json(request)
            .send()
            .await
            .map_err(|e| format!("failed to reach backend: {e}"))?;

        let status = response.status();
        if status.is_success() {
            response
                .json::<ConsultingNote>()
                .await
                .map_err(|e| format!("backend returned an unexpected response: {e}"))
        } else {
            let body_text = response.text().await.unwrap_or_default();
            if let Ok(err) = serde_json::from_str::<ErrorResponse>(&body_text) {
                Err(format!("{} ({})", err.error.message, err.error.code))
            } else {
                Err(format!("backend returned {status}: {body_text}"))
            }
        }
    }

    pub async fn notes_summarize(&self, request: &NotesSummaryRequest) -> Result<NoteSummary, String> {
        let url = format!("{}/api/v1/notes/summarize", self.base_url);
        let response = self
            .http
            .post(&url)
            .timeout(Duration::from_secs(60))
            .json(request)
            .send()
            .await
            .map_err(|e| format!("failed to reach backend: {e}"))?;

        let status = response.status();
        if status.is_success() {
            response
                .json::<NoteSummary>()
                .await
                .map_err(|e| format!("backend returned an unexpected response: {e}"))
        } else {
            let body_text = response.text().await.unwrap_or_default();
            if let Ok(err) = serde_json::from_str::<ErrorResponse>(&body_text) {
                Err(format!("{} ({})", err.error.message, err.error.code))
            } else {
                Err(format!("backend returned {status}: {body_text}"))
            }
        }
    }

    pub async fn notes_ask(&self, request: &NotesAskRequest) -> Result<NotesAskResponse, String> {
        let url = format!("{}/api/v1/notes/ask", self.base_url);
        let response = self
            .http
            .post(&url)
            .timeout(Duration::from_secs(60))
            .json(request)
            .send()
            .await
            .map_err(|e| format!("failed to reach backend: {e}"))?;

        let status = response.status();
        if status.is_success() {
            response
                .json::<NotesAskResponse>()
                .await
                .map_err(|e| format!("backend returned an unexpected response: {e}"))
        } else {
            let body_text = response.text().await.unwrap_or_default();
            if let Ok(err) = serde_json::from_str::<ErrorResponse>(&body_text) {
                Err(format!("{} ({})", err.error.message, err.error.code))
            } else {
                Err(format!("backend returned {status}: {body_text}"))
            }
        }
    }
}

impl Default for BackendClient {
    fn default() -> Self {
        Self::new()
    }
}

/// Extracts every complete SSE frame currently in `buffer`, parses each one's
/// `data:` line as an `AnalysisProgressEvent`, and removes the consumed bytes
/// from `buffer` (leaving any trailing partial frame for the next network
/// chunk). Frames unparseable as `AnalysisProgressEvent` are logged and
/// skipped rather than aborting the whole stream.
///
/// sse-starlette (the backend's SSE implementation) terminates lines with
/// "\r\n", not a bare "\n" — normalizing is done on the whole accumulated
/// buffer (not per network chunk) since a "\r\n" pair can be split across two
/// chunks at the network layer. Without this normalization the "\n\n"
/// frame-boundary search below never matches CRLF input, silently
/// accumulating the whole response instead of yielding any events (caught
/// during manual end-to-end testing: the desktop reported "analysis stream
/// ended without a final result" even though the backend's own response was
/// correct end-to-end — see docs/progress.md Step 10).
fn drain_sse_events(buffer: &mut String) -> Vec<AnalysisProgressEvent> {
    let mut events = Vec::new();
    for (_event_name, data) in drain_raw_sse_frames(buffer) {
        match serde_json::from_str::<AnalysisProgressEvent>(&data) {
            Ok(event) => events.push(event),
            Err(err) => log::warn!("failed to parse SSE analysis event: {err}"),
        }
    }
    events
}

/// Extracts every complete SSE frame currently in `buffer` as
/// `(event_name, data)` pairs — `event_name` is `None` if the frame had no
/// `event:` line (the SSE spec defaults an unlabeled frame to `"message"`,
/// but no caller here relies on that default). Consumed bytes are removed
/// from `buffer`, leaving any trailing partial frame for the next network
/// chunk. Used both for the structured analysis-progress stream
/// (`drain_sse_events` above) and Interview Mode's plain-text answer stream
/// (`BackendClient::ask_stream`), so the CRLF-normalization fix (see
/// `drain_sse_events`'s original doc comment / docs/progress.md Step 10) only
/// has to exist in one place.
fn drain_raw_sse_frames(buffer: &mut String) -> Vec<(Option<String>, String)> {
    if buffer.contains('\r') {
        *buffer = buffer.replace("\r\n", "\n");
    }

    let mut frames = Vec::new();
    while let Some(frame_end) = buffer.find("\n\n") {
        let frame = buffer[..frame_end].to_string();
        buffer.drain(..frame_end + 2);

        let event_name = frame
            .lines()
            .find(|l| l.starts_with("event:"))
            .map(|l| l.trim_start_matches("event:").trim().to_string());

        // Per the SSE spec, a single frame can carry its payload across
        // MULTIPLE "data:" lines, which the receiver joins with "\n" — this
        // is exactly how a delta chunk containing a newline (e.g. the blank
        // line between an intro sentence and a Markdown numbered list) gets
        // encoded by sse_starlette. Taking only the first "data:" line
        // (the previous behavior) silently dropped every such newline,
        // which is what collapsed Interview Mode's numbered-list/paragraph
        // formatting into one run-on paragraph despite the backend and
        // Markdown renderer both being correct — see docs/progress.md.
        let data_lines: Vec<&str> = frame.lines().filter(|l| l.starts_with("data:")).collect();
        if data_lines.is_empty() {
            continue;
        }
        // Per the SSE spec, exactly one leading space after "data:" (if
        // present) is stripped — nothing else. Using a full `.trim()` here
        // would silently eat meaningful trailing whitespace from streamed
        // plain-text answer deltas (e.g. the space between "I" and "have"
        // arriving as two separate chunks), corrupting word boundaries.
        let data = data_lines
            .into_iter()
            .map(|data_line| {
                data_line
                    .trim_start_matches("data:")
                    .strip_prefix(' ')
                    .unwrap_or_else(|| data_line.trim_start_matches("data:"))
            })
            .collect::<Vec<_>>()
            .join("\n");
        frames.push((event_name, data));
    }
    frames
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_crlf_terminated_sse_frames() {
        let mut buffer = "event: transcript\r\ndata: {\"stage\": \"transcript\", \"detail\": \"Processing...\"}\r\n\r\n".to_string();
        let events = drain_sse_events(&mut buffer);
        assert_eq!(events.len(), 1);
        assert_eq!(events[0].stage, "transcript");
        assert!(buffer.is_empty());
    }

    #[test]
    fn parses_lf_terminated_sse_frames() {
        let mut buffer = "event: transcript\ndata: {\"stage\": \"transcript\", \"detail\": \"Processing...\"}\n\n".to_string();
        let events = drain_sse_events(&mut buffer);
        assert_eq!(events.len(), 1);
        assert_eq!(events[0].stage, "transcript");
    }

    #[test]
    fn leaves_trailing_partial_frame_in_buffer() {
        let mut buffer = "event: transcript\r\ndata: {\"stage\": \"transcript\", \"detail\": \"x\"}\r\n\r\nevent: retrieval\r\ndata: {\"stage\"".to_string();
        let events = drain_sse_events(&mut buffer);
        assert_eq!(events.len(), 1);
        assert!(buffer.contains("retrieval"));
    }

    #[test]
    fn parses_multiple_frames_in_one_chunk() {
        let mut buffer = concat!(
            "event: transcript\r\ndata: {\"stage\": \"transcript\", \"detail\": \"a\"}\r\n\r\n",
            "event: retrieval\r\ndata: {\"stage\": \"retrieval\", \"detail\": \"b\"}\r\n\r\n",
        )
        .to_string();
        let events = drain_sse_events(&mut buffer);
        assert_eq!(events.len(), 2);
        assert_eq!(events[0].stage, "transcript");
        assert_eq!(events[1].stage, "retrieval");
    }

    #[test]
    fn extracts_full_result_from_complete_event() {
        let data = serde_json::json!({
            "stage": "complete",
            "detail": "Analysis complete.",
            "result": {
                "session_id": "s1",
                "status": "completed",
                "overall_score": 80,
                "technical_score": 85,
                "communication_score": 75,
                "practical_experience_score": 78,
                "confidence_score": 76,
                "summary": "Good.",
                "strengths": [],
                "weaknesses": [],
                "recommendations": [],
                "questions": [],
                "disclaimer": "AI-generated.",
                "message": ""
            }
        });
        let mut buffer = format!("event: complete\r\ndata: {data}\r\n\r\n");
        let events = drain_sse_events(&mut buffer);
        assert_eq!(events.len(), 1);
        assert!(events[0].result.is_some());
        assert_eq!(events[0].result.as_ref().unwrap().overall_score, 80);
    }

    #[test]
    fn skips_unparseable_frame_without_losing_subsequent_ones() {
        let mut buffer = concat!(
            "event: broken\r\ndata: not valid json\r\n\r\n",
            "event: transcript\r\ndata: {\"stage\": \"transcript\", \"detail\": \"ok\"}\r\n\r\n",
        )
        .to_string();
        let events = drain_sse_events(&mut buffer);
        assert_eq!(events.len(), 1);
        assert_eq!(events[0].stage, "transcript");
    }

    #[test]
    fn empty_buffer_yields_no_events() {
        let mut buffer = String::new();
        let events = drain_sse_events(&mut buffer);
        assert!(events.is_empty());
    }

    #[test]
    fn raw_frames_capture_event_name_and_plain_text_data() {
        let mut buffer = "event: delta\r\ndata: Hello\r\n\r\n".to_string();
        let frames = drain_raw_sse_frames(&mut buffer);
        assert_eq!(frames.len(), 1);
        assert_eq!(frames[0].0.as_deref(), Some("delta"));
        assert_eq!(frames[0].1, "Hello");
    }

    #[test]
    fn raw_frames_handle_done_event_with_empty_data() {
        let mut buffer = "event: done\r\ndata: \r\n\r\n".to_string();
        let frames = drain_raw_sse_frames(&mut buffer);
        assert_eq!(frames.len(), 1);
        assert_eq!(frames[0].0.as_deref(), Some("done"));
        assert_eq!(frames[0].1, "");
    }

    #[test]
    fn raw_frames_parses_multiple_delta_events_in_order() {
        let mut buffer = concat!(
            "event: delta\r\ndata: I \r\n\r\n",
            "event: delta\r\ndata: have\r\n\r\n",
            "event: done\r\ndata: \r\n\r\n",
        )
        .to_string();
        let frames = drain_raw_sse_frames(&mut buffer);
        assert_eq!(frames.len(), 3);
        assert_eq!(frames[0].1, "I ");
        assert_eq!(frames[1].1, "have");
        assert_eq!(frames[2].0.as_deref(), Some("done"));
    }

    #[test]
    fn raw_frames_join_multi_line_data_with_newline() {
        // sse_starlette (the backend's SSE library) encodes a payload that
        // itself contains a newline as multiple "data:" lines within one
        // frame, per the SSE spec — this is exactly how the blank line
        // between an intro sentence and a Markdown numbered list arrives as
        // a single delta. Regression test for the bug where only the first
        // "data:" line was read, silently dropping every such newline and
        // collapsing Interview Mode's formatted answers into one paragraph.
        let mut buffer = "event: delta\r\ndata: .\r\ndata: \r\ndata: \r\n\r\n".to_string();
        let frames = drain_raw_sse_frames(&mut buffer);
        assert_eq!(frames.len(), 1);
        assert_eq!(frames[0].1, ".\n\n");
    }

    #[test]
    fn raw_frames_join_multi_line_data_across_a_full_answer() {
        let mut buffer = concat!(
            "event: delta\r\ndata: Overview.\r\n\r\n",
            "event: delta\r\ndata: \r\ndata: \r\n\r\n",
            "event: delta\r\ndata: 1. Step one\r\n\r\n",
            "event: done\r\ndata: \r\n\r\n",
        )
        .to_string();
        let frames = drain_raw_sse_frames(&mut buffer);
        let joined: String = frames.iter().map(|f| f.1.clone()).collect();
        assert_eq!(joined, "Overview.\n1. Step one");
    }
}
