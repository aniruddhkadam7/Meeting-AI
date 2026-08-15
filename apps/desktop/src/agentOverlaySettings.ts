// Per-agent overlay display settings — position/size/answer display/auto AI
// preferences, kept separate per agent (localStorage key includes agentId) so
// customizing one agent's overlay never affects another's. Mirrors Interview
// Mode's overlaySettings.ts shape/versioning approach but scoped per agent
// and without the interview-specific fields (role/company/job description).

export type OverlaySize = "small" | "medium" | "large";
export type OverlayDensity = "compact" | "comfortable";
export type AnswerDisplay = "chat" | "compact";

export interface AgentOverlaySettings {
  opacity: number; // 0.15 - 1.0
  size: OverlaySize;
  fontSize: number; // px, 12 - 20
  density: OverlayDensity;
  dragEnabled: boolean;
  answerDisplay: AnswerDisplay;
  // When on, a completed question from the live transcript is sent
  // automatically after a short pause, instead of requiring manual Ask.
  autoAI: boolean;
}

export const DEFAULT_AGENT_OVERLAY_SETTINGS: AgentOverlaySettings = {
  opacity: 0.8,
  size: "large",
  fontSize: 14,
  density: "comfortable",
  dragEnabled: true,
  answerDisplay: "chat",
  autoAI: false,
};

export const SIZE_FRACTIONS: Record<OverlaySize, number> = {
  small: 0.45,
  medium: 0.6,
  large: 0.75,
};

const MIN_USABLE_OPACITY = 0.15;

function storageKey(agentId: string): string {
  return `agent:${agentId}:overlay-settings`;
}

export function loadAgentOverlaySettings(agentId: string): AgentOverlaySettings {
  try {
    const raw = window.localStorage.getItem(storageKey(agentId));
    if (!raw) return { ...DEFAULT_AGENT_OVERLAY_SETTINGS };
    const parsed = JSON.parse(raw);
    const merged: AgentOverlaySettings = { ...DEFAULT_AGENT_OVERLAY_SETTINGS, ...parsed };
    merged.opacity = Math.min(1, Math.max(MIN_USABLE_OPACITY, merged.opacity));
    return merged;
  } catch {
    return { ...DEFAULT_AGENT_OVERLAY_SETTINGS };
  }
}

export function saveAgentOverlaySettings(agentId: string, settings: AgentOverlaySettings): void {
  try {
    window.localStorage.setItem(storageKey(agentId), JSON.stringify(settings));
  } catch {
    // localStorage unavailable — settings simply won't persist across restarts.
  }
}
