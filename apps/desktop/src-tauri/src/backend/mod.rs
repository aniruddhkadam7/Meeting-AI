//! HTTP client for the FastAPI backend.
//!
//! This is the ONLY place in the desktop app that makes network calls with
//! interview-derived data, and it only ever sends the finalized transcript (plain
//! text) plus per-question locally-retrieved RAG context (never audio, never the
//! original documents, never embeddings, never partial/in-progress transcript
//! state). Every call here happens because the user explicitly clicked a UI
//! action (Analyze Interview, or a background connectivity check), never
//! automatically as a side effect of recording.

mod client;
mod config;
mod types;

pub use client::BackendClient;
pub use config::backend_url;
pub use types::{
    AgentAskRequest, AgentAskResponse, AgentConversationTurn, AgentPersonalization,
    AgentRetrievedChunk, AnalysisProgressEvent, AskRequest, AskResponse, AskRetrievedChunk,
    ConsultingAskRequest, ConsultingAskResponse, ConsultingConversationTurn, ConsultingNote,
    ConsultingRetrievedChunk, ConsultingSummaryRequest, ConsultingTurnIn, ConversationTurn,
    InterviewAnalysisRequest, NoteContext, NoteSummary, NotesAskRequest, NotesAskResponse,
    NotesSummaryRequest, OverallInterviewAnalysis, QuestionAnalysis, RetrievedSourceRef,
    SalesAskRequest, SalesAskResponse, SalesCallSummary, SalesConversationTurn,
    SalesRetrievedChunk, SalesSummaryRequest, SalesTurnIn, SetupAnalysisRequest,
    SetupAnalysisResponse, WireAudioSource, WireCandidateContext, WireQuestionAnswer,
    WireRetrievedChunk, WireTranscript, WireTranscriptSegment,
};
