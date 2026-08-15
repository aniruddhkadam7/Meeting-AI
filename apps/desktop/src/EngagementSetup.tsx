import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import { readFile } from "@tauri-apps/plugin-fs";
import { Button } from "./ui";

interface ConsultingTurn {
  speaker: "CONSULTANT" | "CLIENT";
  text: string;
}

interface ConsultingSessionEntry {
  id: string;
  started_at_ms: number;
  ended_at_ms: number;
  turns: ConsultingTurn[];
  notes: unknown;
}

interface Engagement {
  id: string;
  client_name: string;
  project_name: string | null;
  created_at_ms: number;
  sessions: ConsultingSessionEntry[];
}

interface Props {
  onStart: () => void;
}

export function EngagementSetup({ onStart }: Props) {
  const [engagements, setEngagements] = useState<Engagement[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);
  const [starting, setStarting] = useState(false);

  const [clientName, setClientName] = useState("");
  const [projectName, setProjectName] = useState("");
  const [fileName, setFileName] = useState<string | null>(null);
  const [fileBytes, setFileBytes] = useState<number[] | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    try {
      const list = await invoke<Engagement[]>("list_engagements");
      setEngagements(list);
    } catch (e) {
      setError(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    refresh();
  }, [refresh]);

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

  const beginSession = useCallback(
    async (engagement: Engagement) => {
      setStarting(true);
      setError(null);
      try {
        let context: string | null = null;
        try {
          context = await invoke<string | null>("get_engagement_context", { engagementId: engagement.id });
        } catch {
          context = null;
        }

        window.localStorage.setItem(
          "consulting-mode:active-engagement",
          JSON.stringify({
            engagementId: engagement.id,
            clientName: engagement.client_name,
            projectName: engagement.project_name || "",
            context: context || "",
          }),
        );

        await invoke("clear_consulting_session").catch(() => {});
        await invoke("start_system_audio_capture").catch((e) => {
          if (String(e) !== "capture already running") throw e;
        });
        await invoke("show_consulting_overlay");
        onStart();
      } catch (e) {
        setError(String(e));
      } finally {
        setStarting(false);
      }
    },
    [onStart],
  );

  const createAndStart = useCallback(async () => {
    if (!clientName.trim()) {
      setError("Client name is required.");
      return;
    }
    setCreating(true);
    setError(null);
    try {
      const engagement = await invoke<Engagement>("create_engagement", {
        clientName: clientName.trim(),
        projectName: projectName.trim() || null,
      });

      if (fileBytes && fileName) {
        invoke("upload_document", {
          filename: fileName,
          bytes: fileBytes,
          documentType: "OTHER",
        }).catch((e) => console.error("Failed to upload engagement document:", e));
      }

      await refresh();
      await beginSession(engagement);
    } catch (e) {
      setError(String(e));
    } finally {
      setCreating(false);
    }
  }, [clientName, projectName, fileBytes, fileName, refresh, beginSession]);

  return (
    <div className="setup-shell">
      <section className="setup-hero">
        <div className="setup-hero-text">
          <h1 className="setup-title">Consulting</h1>
          <p className="setup-subtitle">Resume an engagement or start a new one</p>
        </div>
      </section>

      {error && <p className="error">{error}</p>}

      <div className="setup-section">
        <div className="setup-section-head">
          <span className="setup-section-label">New Engagement</span>
        </div>
        <div className="setup-section-body">
          <div className="setup-identity">
            <div className="setup-identity-field">
              <label htmlFor="eng-client">Client Name</label>
              <input
                id="eng-client"
                className="setup-input"
                value={clientName}
                onChange={(e) => setClientName(e.target.value)}
                placeholder="e.g. Northwind Corp"
              />
            </div>
            <div className="setup-identity-field">
              <label htmlFor="eng-project">Project</label>
              <input
                id="eng-project"
                className="setup-input"
                value={projectName}
                onChange={(e) => setProjectName(e.target.value)}
                placeholder="e.g. Platform Migration"
              />
            </div>
          </div>

          {fileName ? (
            <div className="setup-file-chip">
              <span className="setup-file-name">{fileName}</span>
              <button className="link-button" onClick={() => { setFileName(null); setFileBytes(null); }}>
                Remove
              </button>
            </div>
          ) : (
            <Button variant="secondary" size="sm" onClick={pickFile}>
              Upload a document (optional)
            </Button>
          )}

          <div>
            <Button variant="primary" onClick={createAndStart} disabled={creating || starting}>
              {creating ? "Creating…" : "Create & Start Session"}
            </Button>
          </div>
        </div>
      </div>

      <div className="setup-section-head">
        <span className="setup-section-label">Existing Engagements</span>
      </div>

      {loading ? (
        <p className="hint small">Loading engagements…</p>
      ) : engagements.length === 0 ? (
        <p className="history-empty">No engagements yet. Create one above to get started.</p>
      ) : (
        <div className="history-entries">
          {engagements.map((eng) => (
            <div className="history-entry-card" key={eng.id} style={{ cursor: "default" }}>
              <div className="history-entry-top">
                <span className="history-entry-title">
                  {[eng.client_name, eng.project_name].filter(Boolean).join(" · ")}
                </span>
                <span className="history-entry-duration">{eng.sessions.length} session(s)</span>
              </div>
              <div style={{ marginTop: "0.5rem" }}>
                <Button variant="secondary" size="sm" onClick={() => beginSession(eng)} disabled={starting}>
                  {starting ? "Starting…" : "Resume Session"}
                </Button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
