use tauri::{AppHandle, Manager};

use crate::agents::model::Agent;
use crate::agents::store::AgentStore;
use crate::auth;

use super::client::{CloudSyncClient, SyncedAgent};

fn to_synced(agent: &Agent) -> SyncedAgent {
    SyncedAgent {
        client_id: agent.id.clone(),
        name: agent.name.clone(),
        base_role: agent
            .base_role
            .map(|r| serde_json::to_value(r).unwrap().as_str().unwrap().to_string()),
        description: agent.description.clone(),
        custom_instructions: agent.custom_instructions.clone(),
        personalization: serde_json::to_value(agent.personalization).unwrap_or_default(),
        created_at_ms: agent.created_at_ms,
        updated_at_ms: agent.updated_at_ms,
        deleted: false,
    }
}

fn from_synced(synced: &SyncedAgent) -> Option<Agent> {
    let base_role = match &synced.base_role {
        Some(role_str) => serde_json::from_value(serde_json::Value::String(role_str.clone())).ok(),
        None => None,
    };
    let personalization = serde_json::from_value(synced.personalization.clone()).unwrap_or_default();
    Some(Agent {
        id: synced.client_id.clone(),
        name: synced.name.clone(),
        base_role,
        description: synced.description.clone(),
        custom_instructions: synced.custom_instructions.clone(),
        personalization,
        created_at_ms: synced.created_at_ms,
        updated_at_ms: synced.updated_at_ms,
    })
}

/// Pushes every local agent, then pulls the cloud's set and merges in
/// anything newer than (or absent from) the local store, by `updated_at_ms`.
/// Best-effort: returns a clear error string on failure (network down, not
/// signed in, cloud not configured), but callers treat that as "sync
/// skipped," never as a reason to fail the agent CRUD operation that
/// triggered it — see the module doc comment in `mod.rs`.
#[tauri::command]
pub async fn sync_agents_now(
    app: AppHandle,
    store: tauri::State<'_, AgentStore>,
) -> Result<usize, String> {
    if !auth::is_configured() {
        return Ok(0);
    }
    let Some(token) = auth::get_valid_access_token().await? else {
        return Ok(0);
    };

    let client = CloudSyncClient::new();

    let local_agents: Vec<Agent> = {
        let mut guard = store.0.lock().map_err(|e| e.to_string())?;
        if guard.is_empty() {
            *guard = crate::agents::store::load(&app);
        }
        guard.clone()
    };

    let synced_local: Vec<SyncedAgent> = local_agents.iter().map(to_synced).collect();
    client.push_agents(&token, &synced_local).await?;

    let cloud_agents = client.pull_agents(&token).await?;

    let mut guard = store.0.lock().map_err(|e| e.to_string())?;
    let merged_count = merge_cloud_into_local(&mut guard, &cloud_agents);
    if merged_count > 0 {
        let path = app
            .path()
            .app_data_dir()
            .map_err(|e| format!("failed to resolve app data directory: {e}"))?
            .join("agents.json");
        let json = serde_json::to_string_pretty(&*guard).map_err(|e| e.to_string())?;
        std::fs::write(&path, json).map_err(|e| e.to_string())?;
    }

    Ok(merged_count)
}

/// Merges `cloud_agents` into `local`, in place, last-write-wins by
/// `updated_at_ms`. A cloud row strictly newer than its local counterpart
/// (matched by `client_id` == local `Agent.id`) overwrites it; a cloud row
/// with no local counterpart is appended; a cloud row that is not newer is
/// left untouched (the next push will bring the cloud row up to date).
/// Returns how many local rows were added/updated. Pure and side-effect-free
/// so it's unit-testable without a Tauri `AppHandle` or network access.
fn merge_cloud_into_local(local: &mut Vec<Agent>, cloud_agents: &[SyncedAgent]) -> usize {
    let mut merged_count = 0;
    for synced in cloud_agents {
        let local_match = local.iter().position(|a| a.id == synced.client_id);
        match local_match {
            Some(idx) if local[idx].updated_at_ms >= synced.updated_at_ms => {
                // Local copy is newer or equal — keep it, cloud will get it
                // on the next push.
            }
            Some(idx) => {
                if let Some(updated) = from_synced(synced) {
                    local[idx] = updated;
                    merged_count += 1;
                }
            }
            None => {
                if let Some(new_agent) = from_synced(synced) {
                    local.push(new_agent);
                    merged_count += 1;
                }
            }
        }
    }
    merged_count
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::agents::model::Personalization;

    fn agent(id: &str, name: &str, updated_at_ms: u64) -> Agent {
        Agent {
            id: id.to_string(),
            name: name.to_string(),
            base_role: None,
            description: None,
            custom_instructions: None,
            personalization: Personalization::default(),
            created_at_ms: updated_at_ms,
            updated_at_ms,
        }
    }

    fn synced(client_id: &str, name: &str, updated_at_ms: u64) -> SyncedAgent {
        SyncedAgent {
            client_id: client_id.to_string(),
            name: name.to_string(),
            base_role: None,
            description: None,
            custom_instructions: None,
            personalization: serde_json::to_value(Personalization::default()).unwrap(),
            created_at_ms: updated_at_ms,
            updated_at_ms,
            deleted: false,
        }
    }

    #[test]
    fn cloud_agent_absent_locally_is_added() {
        let mut local = vec![];
        let cloud = vec![synced("agent-1", "Cloud Agent", 100)];
        let count = merge_cloud_into_local(&mut local, &cloud);
        assert_eq!(count, 1);
        assert_eq!(local.len(), 1);
        assert_eq!(local[0].name, "Cloud Agent");
    }

    #[test]
    fn newer_cloud_agent_overwrites_older_local_agent() {
        let mut local = vec![agent("agent-1", "Old Local Name", 100)];
        let cloud = vec![synced("agent-1", "Newer Cloud Name", 200)];
        let count = merge_cloud_into_local(&mut local, &cloud);
        assert_eq!(count, 1);
        assert_eq!(local[0].name, "Newer Cloud Name");
        assert_eq!(local[0].updated_at_ms, 200);
    }

    #[test]
    fn older_cloud_agent_does_not_overwrite_newer_local_agent() {
        let mut local = vec![agent("agent-1", "Newer Local Name", 200)];
        let cloud = vec![synced("agent-1", "Stale Cloud Name", 100)];
        let count = merge_cloud_into_local(&mut local, &cloud);
        assert_eq!(count, 0);
        assert_eq!(local[0].name, "Newer Local Name");
    }

    #[test]
    fn equal_timestamps_prefer_local_and_report_no_merge() {
        let mut local = vec![agent("agent-1", "Local Name", 150)];
        let cloud = vec![synced("agent-1", "Cloud Name", 150)];
        let count = merge_cloud_into_local(&mut local, &cloud);
        assert_eq!(count, 0);
        assert_eq!(local[0].name, "Local Name");
    }

    #[test]
    fn unrelated_agents_are_both_kept() {
        let mut local = vec![agent("agent-1", "Local Only", 100)];
        let cloud = vec![synced("agent-2", "Cloud Only", 100)];
        let count = merge_cloud_into_local(&mut local, &cloud);
        assert_eq!(count, 1);
        assert_eq!(local.len(), 2);
    }
}
