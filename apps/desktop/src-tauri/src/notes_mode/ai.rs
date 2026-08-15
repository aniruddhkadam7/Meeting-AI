//! AI operations for Notes: summarizing a note, and asking a question with
//! one or more notes as optional context. Stateless — no session concept.

use crate::backend::{BackendClient, NoteContext, NotesAskRequest, NotesSummaryRequest};

#[derive(Debug, serde::Deserialize)]
pub struct NoteAskContext {
    pub title: Option<String>,
    pub body: String,
}

#[tauri::command]
pub async fn summarize_note(
    title: Option<String>,
    body: String,
) -> Result<crate::backend::NoteSummary, String> {
    let client = BackendClient::new();
    client.notes_summarize(&NotesSummaryRequest { title, body }).await
}

#[tauri::command]
pub async fn ask_about_notes(
    question: String,
    notes: Vec<NoteAskContext>,
) -> Result<crate::backend::NotesAskResponse, String> {
    let client = BackendClient::new();
    client
        .notes_ask(&NotesAskRequest {
            question,
            notes: notes.into_iter().map(|n| NoteContext { title: n.title, body: n.body }).collect(),
        })
        .await
}
