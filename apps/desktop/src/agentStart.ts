import { invoke } from "@tauri-apps/api/core";
import { Agent } from "./types";

/// Shared "Start Conversation" flow for an agent — used from both the agent
/// card's quick Start button and the workspace header's Start button, so
/// there is exactly one place that seeds the active-agent info, starts audio
/// capture, and opens this agent's overlay window.
export async function startAgentConversation(agent: Agent): Promise<void> {
  window.localStorage.setItem(
    `agent:${agent.id}:active`,
    JSON.stringify({
      id: agent.id,
      name: agent.name,
      baseRole: agent.baseRole,
      description: agent.description,
      personalization: agent.personalization,
    }),
  );
  await invoke("start_system_audio_capture").catch((e) => {
    if (String(e) !== "capture already running") throw e;
  });
  await invoke("show_agent_overlay", { agentId: agent.id, agentName: agent.name });
}
