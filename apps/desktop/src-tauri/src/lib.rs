mod agents;
mod analytics;
mod analyzer;
// Public so the `audio_probe` binary (src/bin/audio_probe.rs) can drive the
// real capture path when measuring the pipeline, rather than a copy of it that
// could drift from what actually ships.
pub mod audio;
mod auth;
mod backend;
mod cloud_sync;
mod commands;
mod consulting_mode;
mod history;
mod interview_mode;
mod notes_mode;
mod overlay_window;
mod rag;
mod sales_mode;
mod state;
mod tls_init;
mod updater;
// Public alongside `audio` so `src/bin/pipeline_test.rs` can drive the real
// recording pipeline headlessly instead of a reimplementation of it.
pub mod stt;
pub mod transcript;
mod windows_capture_protection;

use tauri::Manager;

use state::AppState;

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    env_logger::init();
    tls_init::ensure_installed();

    tauri::Builder::default()
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_fs::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(
            tauri_plugin_global_shortcut::Builder::new()
                .with_handler(|app, _shortcut, event| {
                    // Only react on key-down, not key-up, so holding the
                    // combination doesn't repeatedly toggle the overlay.
                    if event.state() == tauri_plugin_global_shortcut::ShortcutState::Pressed {
                        if let Err(err) = interview_mode::toggle_overlay_window(app) {
                            log::warn!("failed to toggle Interview Mode overlay via hotkey: {err}");
                        }
                    }
                })
                .build(),
        )
        .manage(AppState::default())
        .manage(history::HistoryStore::default())
        .manage(sales_mode::history::SalesHistoryStore::default())
        .manage(consulting_mode::history::ConsultingHistoryStore::default())
        .manage(agents::store::AgentStore::default())
        .manage(agents::history::AgentHistoryStore::default())
        .manage(analytics::AnalyticsQueue::default())
        .setup(|app| {
            use tauri_plugin_global_shortcut::GlobalShortcutExt;
            // Ctrl+Shift+Space: show/hide the Interview Mode overlay (spec
            // section 19/21). Registration failure (e.g. the combination is
            // already claimed by another application) is logged, not fatal —
            // the overlay remains reachable from the main window's button.
            if let Err(err) = app.global_shortcut().register("Ctrl+Shift+Space") {
                log::warn!("failed to register Ctrl+Shift+Space global hotkey: {err}");
            }
            // Spawn the local RAG service in the background; the app remains
            // usable for recording/transcription immediately even while this
            // is still starting up or if it's unavailable entirely (see
            // rag::process::RagServiceHandle::spawn).
            let handle = app.handle().clone();
            std::thread::spawn(move || match rag::RagServiceHandle::spawn() {
                Ok(service) => {
                    if service.is_some() {
                        rag::wait_until_healthy_default();
                    }
                    let state = handle.state::<AppState>();
                    let lock_result = state.rag_service.lock();
                    if let Ok(mut slot) = lock_result {
                        *slot = service;
                    }
                }
                Err(err) => {
                    log::error!("failed to start RAG service: {err}");
                }
            });

            // Analytics: record app_opened once at launch, then flush the
            // queue on a background timer for the lifetime of the app.
            // Flushing is a no-op (events stay queued) until the user is
            // signed in — see analytics::queue::flush_events.
            {
                let analytics_state = app.state::<analytics::AnalyticsQueue>();
                analytics::track(
                    &analytics_state,
                    "app_opened",
                    serde_json::json!({ "os": "windows" }),
                );
            }
            let analytics_handle = app.handle().clone();
            tauri::async_runtime::spawn(async move {
                loop {
                    tokio::time::sleep(std::time::Duration::from_secs(60)).await;
                    let queue = analytics_handle.state::<analytics::AnalyticsQueue>();
                    analytics::flush_events(&queue).await;
                }
            });

            Ok(())
        })
        .invoke_handler(tauri::generate_handler![
            commands::list_output_devices,
            commands::list_input_devices,
            commands::start_system_audio_capture,
            commands::pause_recording,
            commands::resume_recording,
            commands::stop_audio_capture,
            commands::get_current_session,
            commands::get_recording_state,
            commands::start_new_interview,
            commands::clear_transcript,
            commands::export_transcript_txt,
            commands::export_transcript_json,
            commands::check_backend_connection,
            commands::analyze_interview,
            commands::check_rag_connection,
            commands::analyze_setup_context,
            commands::upload_document,
            commands::get_document_text,
            commands::list_documents,
            commands::delete_document,
            commands::clear_knowledge_base,
            commands::knowledge_base_status,
            commands::search_knowledge_base,
            interview_mode::commands::show_interview_overlay,
            interview_mode::commands::hide_interview_overlay,
            interview_mode::commands::toggle_interview_overlay,
            interview_mode::commands::ask_interview_question,
            interview_mode::commands::set_overlay_always_on_top,
            interview_mode::commands::resize_interview_overlay,
            history::list_interview_history,
            history::archive_interview_session,
            history::delete_interview_history_entry,
            sales_mode::commands::show_sales_overlay,
            sales_mode::commands::hide_sales_overlay,
            sales_mode::commands::toggle_sales_overlay,
            sales_mode::commands::ask_sales_question,
            sales_mode::commands::track_sales_item,
            sales_mode::commands::clear_sales_session,
            sales_mode::commands::end_sales_call,
            sales_mode::history::list_sales_history,
            sales_mode::history::archive_sales_call,
            sales_mode::history::delete_sales_history_entry,
            consulting_mode::commands::show_consulting_overlay,
            consulting_mode::commands::hide_consulting_overlay,
            consulting_mode::commands::toggle_consulting_overlay,
            consulting_mode::commands::ask_consulting_question,
            consulting_mode::commands::track_consulting_item,
            consulting_mode::commands::clear_consulting_session,
            consulting_mode::commands::end_consulting_session,
            consulting_mode::history::list_engagements,
            consulting_mode::history::create_engagement,
            consulting_mode::history::get_engagement_context,
            consulting_mode::history::archive_consulting_session,
            consulting_mode::history::delete_engagement,
            notes_mode::store::list_notes,
            notes_mode::store::get_note,
            notes_mode::store::create_note,
            notes_mode::store::update_note,
            notes_mode::store::delete_note,
            notes_mode::store::search_notes,
            notes_mode::dictation::start_note_dictation,
            notes_mode::dictation::stop_note_dictation,
            notes_mode::ai::summarize_note,
            notes_mode::ai::ask_about_notes,
            agents::store::list_agents,
            agents::store::get_agent,
            agents::store::create_agent,
            agents::store::update_agent,
            agents::store::delete_agent,
            agents::history::list_agent_history,
            agents::history::archive_agent_conversation,
            agents::history::delete_agent_history_entry,
            agents::ask::ask_agent_question,
            agents::overlay::show_agent_overlay,
            agents::overlay::hide_agent_overlay,
            agents::overlay::toggle_agent_overlay,
            agents::overlay::resize_agent_overlay,
            agents::overlay::set_agent_overlay_always_on_top,
            auth::commands::auth_cloud_configured,
            auth::commands::auth_sign_up,
            auth::commands::auth_sign_in,
            auth::commands::auth_sign_out,
            auth::commands::auth_get_session,
            cloud_sync::commands::sync_agents_now,
            updater::check_for_update,
            updater::install_update_and_restart,
        ])
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
