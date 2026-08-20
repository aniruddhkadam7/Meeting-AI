import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import { readFile } from "@tauri-apps/plugin-fs";
import { Button } from "./ui";
import {
  Agent,
  AgentPersonalization,
  DEFAULT_AGENT_PERSONALIZATION,
  PREDEFINED_ROLES,
  PredefinedRole,
} from "./types";
import { buildPredefinedDescription, roleQuestions } from "./agentRoleQuestions";
import { PersonalizationEditor } from "./AgentCreate";
import { syncAgentsInBackground } from "./cloudSync";

type CreationMode = "PREDEFINED" | "CUSTOM";

interface Props {
  onCreated: (agent: Agent) => void;
  onClose: () => void;
}

/// The entire Custom Agents creation surface, as one modal — no wizard, no
/// nested screens. Choose Predefined Role (a couple of optional, plain-
/// language questions) or Custom Agent (name + a few optional fields).
/// Nothing here ever asks the user to write or see a system prompt; Smallbird
/// composes that internally (apps/backend/app/services/agent_prompt_builder.py).
export function AgentCreateModal({ onCreated, onClose }: Props) {
  const [mode, setMode] = useState<CreationMode>("PREDEFINED");
  const [predefinedRole, setPredefinedRole] = useState<PredefinedRole>(PREDEFINED_ROLES[0].value);
  const [roleAnswers, setRoleAnswers] = useState<Record<string, string>>({});

  const [customName, setCustomName] = useState("");
  const [description, setDescription] = useState("");
  const [customInstructions, setCustomInstructions] = useState("");
  const [showAdvanced, setShowAdvanced] = useState(false);

  const [personalization, setPersonalization] = useState<AgentPersonalization>(DEFAULT_AGENT_PERSONALIZATION);
  const [showPersonalization, setShowPersonalization] = useState(false);
  const [showKnowledge, setShowKnowledge] = useState(false);

  const [fileName, setFileName] = useState<string | null>(null);
  const [fileBytes, setFileBytes] = useState<number[] | null>(null);

  const [creating, setCreating] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setRoleAnswers({});
  }, [predefinedRole]);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !creating) onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose, creating]);

  const pickFile = useCallback(async () => {
    setError(null);
    try {
      const selected = await open({
        multiple: false,
        filters: [{ name: "Documents", extensions: ["pdf", "docx", "txt", "md", "markdown"] }],
      });
      if (!selected || Array.isArray(selected)) return;
      const bytes = await readFile(selected);
      const name = selected.split(/[\\/]/).pop() ?? "document";
      setFileName(name);
      setFileBytes(Array.from(bytes));
    } catch (e) {
      setError(String(e));
    }
  }, []);

  const clearFile = useCallback(() => {
    setFileName(null);
    setFileBytes(null);
  }, []);

  const create = useCallback(async () => {
    setError(null);

    const isPredefined = mode === "PREDEFINED";
    const name = isPredefined
      ? PREDEFINED_ROLES.find((r) => r.value === predefinedRole)?.label ?? "Agent"
      : customName.trim();

    if (!isPredefined && !name) {
      setError("Give your agent a name.");
      return;
    }

    setCreating(true);
    try {
      const agent = await invoke<Agent>("create_agent", {
        input: {
          name,
          // Predefined Role always carries a role persona; Custom Agent is a
          // true blank slate (no baseRole) so the backend falls back to
          // GENERIC_PERSONA and relies only on the user's own name/description/
          // instructions — this is what actually distinguishes the two modes.
          baseRole: isPredefined ? predefinedRole : null,
          description: isPredefined ? buildPredefinedDescription(predefinedRole, roleAnswers) : description.trim() || null,
          customInstructions: isPredefined ? null : customInstructions.trim() || null,
          personalization,
        },
      });

      if (fileBytes && fileName) {
        invoke("upload_document", {
          filename: fileName,
          bytes: fileBytes,
          documentType: "OTHER",
          agentId: agent.id,
        }).catch((e) => console.error("Failed to upload agent knowledge document:", e));
      }

      syncAgentsInBackground();

      onCreated(agent);
    } catch (e) {
      setError(String(e));
    } finally {
      setCreating(false);
    }
  }, [
    mode,
    predefinedRole,
    roleAnswers,
    customName,
    description,
    customInstructions,
    personalization,
    fileBytes,
    fileName,
    onCreated,
  ]);

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && !creating && onClose()}>
      <div className="modal-panel agent-create-modal" role="dialog" aria-modal="true" aria-label="Create Agent">
        <header className="modal-header">
          <h1 className="setup-title">Create Agent</h1>
          <button className="modal-close-btn" onClick={onClose} disabled={creating} title="Close" aria-label="Close">
            ✕
          </button>
        </header>

        {error && <p className="error">{error}</p>}

        <div className="agent-mode-toggle">
          <button
            className={`agent-mode-tab${mode === "PREDEFINED" ? " active" : ""}`}
            onClick={() => setMode("PREDEFINED")}
          >
            Predefined Role
          </button>
          <button className={`agent-mode-tab${mode === "CUSTOM" ? " active" : ""}`} onClick={() => setMode("CUSTOM")}>
            Custom Agent
          </button>
        </div>

        <div className="modal-body">
          {mode === "PREDEFINED" ? (
            <>
              <div className="setup-identity-field">
                <select
                  className="setup-input"
                  aria-label="Role"
                  value={predefinedRole}
                  onChange={(e) => setPredefinedRole(e.target.value as PredefinedRole)}
                >
                  {PREDEFINED_ROLES.map((r) => (
                    <option key={r.value} value={r.value}>
                      {r.label}
                    </option>
                  ))}
                </select>
              </div>

              <div className="agent-role-questions">
                {roleQuestions(predefinedRole).map((q) => (
                  <input
                    key={q.key}
                    className="setup-input"
                    aria-label={q.placeholder}
                    value={roleAnswers[q.key] ?? ""}
                    onChange={(e) => setRoleAnswers((prev) => ({ ...prev, [q.key]: e.target.value }))}
                    placeholder={q.placeholder}
                  />
                ))}
              </div>
            </>
          ) : (
            <>
              <div className="setup-identity-field">
                <input
                  className="setup-input"
                  aria-label="Agent name"
                  value={customName}
                  onChange={(e) => setCustomName(e.target.value)}
                  placeholder="Agent name"
                />
              </div>

              <div className="setup-identity-field">
                <textarea
                  className="setup-input"
                  rows={2}
                  value={description}
                  onChange={(e) => setDescription(e.target.value)}
                  placeholder="What should this agent help with?"
                />
                {!showAdvanced && (
                  <button className="link-button setup-add-more" onClick={() => setShowAdvanced(true)}>
                    + Custom instructions
                  </button>
                )}
              </div>

              {showAdvanced && (
                <div className="setup-identity-field">
                  <textarea
                    className="setup-input"
                    rows={2}
                    value={customInstructions}
                    onChange={(e) => setCustomInstructions(e.target.value)}
                    placeholder="Custom instructions"
                  />
                </div>
              )}
            </>
          )}

          {showKnowledge ? (
            fileName ? (
              <div className="setup-file-chip">
                <span className="setup-file-name">{fileName}</span>
                <button className="link-button" onClick={clearFile}>
                  Remove
                </button>
              </div>
            ) : (
              <Button variant="secondary" size="sm" onClick={pickFile}>
                Upload a document
              </Button>
            )
          ) : (
            <button className="link-button setup-add-more" onClick={() => setShowKnowledge(true)}>
              + Knowledge
            </button>
          )}

          {showPersonalization ? (
            <PersonalizationEditor value={personalization} onChange={setPersonalization} />
          ) : (
            <button className="link-button setup-add-more" onClick={() => setShowPersonalization(true)}>
              + Personalize
            </button>
          )}
        </div>

        <footer className="modal-footer">
          <Button variant="ghost" onClick={onClose} disabled={creating}>
            Cancel
          </Button>
          <Button variant="primary" onClick={create} disabled={creating}>
            {creating ? "Creating…" : "Create Agent"}
          </Button>
        </footer>
      </div>
    </div>
  );
}
