import { invoke } from "@tauri-apps/api/core";

/// Best-effort agent sync, fired after any local agent mutation (create,
/// rename, delete, personalize). Never awaited by callers and never throws —
/// if the user isn't signed in or WhitedotAI Cloud isn't configured, the backend
/// command itself returns 0 immediately; any real failure (network down) is
/// swallowed here since a sync hiccup must never block editing an agent.
export function syncAgentsInBackground(): void {
  invoke("sync_agents_now").catch(() => {
    // Intentionally silent — see doc comment above.
  });
}
