import { AgentPersonalization } from "./types";

interface PersonalizationEditorProps {
  value: AgentPersonalization;
  onChange: (value: AgentPersonalization) => void;
}

/// Shared by AgentCreateModal (creation) and AgentWorkspace's Personalization
/// tab (editing an existing agent) so the two never drift apart.
export function PersonalizationEditor({ value, onChange }: PersonalizationEditorProps) {
  const set = <K extends keyof AgentPersonalization>(key: K, v: AgentPersonalization[K]) =>
    onChange({ ...value, [key]: v });

  return (
    <div className="setup-section">
      <div className="setup-section-body">
      <div className="setup-identity">
        <div className="setup-identity-field">
          <label htmlFor="agent-answer-length">Answer Length</label>
          <select
            id="agent-answer-length"
            className="setup-input"
            value={value.answerLength}
            onChange={(e) => set("answerLength", e.target.value as AgentPersonalization["answerLength"])}
          >
            <option value="adaptive">Adaptive</option>
            <option value="concise">Concise</option>
            <option value="balanced">Balanced</option>
            <option value="detailed">Detailed</option>
          </select>
        </div>
        <div className="setup-identity-field">
          <label htmlFor="agent-response-style">Response Style</label>
          <select
            id="agent-response-style"
            className="setup-input"
            value={value.responseStyle}
            onChange={(e) => set("responseStyle", e.target.value as AgentPersonalization["responseStyle"])}
          >
            <option value="natural">Natural</option>
            <option value="professional">Professional</option>
            <option value="friendly">Friendly</option>
            <option value="technical">Technical</option>
          </select>
        </div>
      </div>
      <div className="setup-identity">
        <div className="setup-identity-field">
          <label htmlFor="agent-answer-format">Answer Format</label>
          <select
            id="agent-answer-format"
            className="setup-input"
            value={value.answerFormat}
            onChange={(e) => set("answerFormat", e.target.value as AgentPersonalization["answerFormat"])}
          >
            <option value="adaptive">Adaptive</option>
            <option value="paragraph">Paragraph</option>
            <option value="bullets">Bullets</option>
            <option value="stepByStep">Step-by-step</option>
          </select>
        </div>
        <div className="setup-identity-field">
          <label htmlFor="agent-live-assistance">Live Assistance</label>
          <select
            id="agent-live-assistance"
            className="setup-input"
            value={value.liveAssistance}
            onChange={(e) => set("liveAssistance", e.target.value as AgentPersonalization["liveAssistance"])}
          >
            <option value="manual">Manual</option>
            <option value="suggest">Suggest</option>
            <option value="auto">Auto</option>
          </select>
        </div>
      </div>
      </div>
    </div>
  );
}
