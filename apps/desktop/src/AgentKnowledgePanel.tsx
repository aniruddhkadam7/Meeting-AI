import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import { readFile } from "@tauri-apps/plugin-fs";
import type { DocumentMetadata, KnowledgeBaseStatus } from "./types";
import { Badge, Button, Card, EmptyState, StatusDot } from "./ui";

const DOC_STATUS_TONE: Record<string, "success" | "danger" | "warning" | "neutral"> = {
  READY: "success",
  ERROR: "danger",
  UPLOADING: "warning",
  EXTRACTING: "warning",
  CLEANING: "warning",
  CHUNKING: "warning",
  EMBEDDING: "warning",
  INDEXING: "warning",
};

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

interface Props {
  agentId: string;
}

/// This agent's own Knowledge tab — every document uploaded here is scoped
/// to `agentId` (never the global knowledge base Interview/Sales/Consulting
/// Mode share, and never another agent's documents; see
/// packages/rag/app/vector_store.py's agent_id column). Deliberately no
/// document-type picker or any RAG/embedding/chunking concept shown — the
/// user just uploads a file, per the "no technical RAG configuration
/// exposed" requirement.
export function AgentKnowledgePanel({ agentId }: Props) {
  const [ragAvailable, setRagAvailable] = useState<boolean | null>(null);
  const [documents, setDocuments] = useState<DocumentMetadata[]>([]);
  const [kbStatus, setKbStatus] = useState<KnowledgeBaseStatus | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const available = await invoke<boolean>("check_rag_connection");
      setRagAvailable(available);
      if (!available) return;
      const [docs, status] = await Promise.all([
        invoke<DocumentMetadata[]>("list_documents", { agentId }),
        invoke<KnowledgeBaseStatus>("knowledge_base_status", { agentId }),
      ]);
      setDocuments(docs);
      setKbStatus(status);
    } catch {
      setRagAvailable(false);
    }
  }, [agentId]);

  useEffect(() => {
    refresh();
    const interval = window.setInterval(refresh, 5000);
    return () => window.clearInterval(interval);
  }, [refresh]);

  const uploadDocument = useCallback(async () => {
    setError(null);
    try {
      const selected = await open({
        multiple: false,
        filters: [{ name: "Documents", extensions: ["pdf", "docx", "txt", "md", "markdown"] }],
      });
      if (!selected || Array.isArray(selected)) return;

      setUploading(true);
      const bytes = await readFile(selected);
      const filename = selected.split(/[\\/]/).pop() ?? "document";

      await invoke("upload_document", {
        filename,
        bytes: Array.from(bytes),
        documentType: "OTHER",
        agentId,
      });
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setUploading(false);
    }
  }, [agentId, refresh]);

  const removeDocument = useCallback(
    async (documentId: string) => {
      setError(null);
      try {
        await invoke("delete_document", { documentId });
        await refresh();
      } catch (e) {
        setError(String(e));
      }
    },
    [refresh],
  );

  const clearAll = useCallback(async () => {
    setError(null);
    try {
      await invoke("clear_knowledge_base", { agentId });
      await refresh();
    } catch (e) {
      setError(String(e));
    }
  }, [agentId, refresh]);

  if (ragAvailable === false) {
    return (
      <Card>
        <EmptyState
          icon="⚠️"
          title="Knowledge tools aren't available right now"
          description="Try again in a moment. This agent still works without documents."
        />
      </Card>
    );
  }

  return (
    <div className="prep-panel">
      <Card title="Upload Knowledge">
        <div className="upload-dropzone">
          <span className="upload-dropzone-icon">📄</span>
          <Button variant="primary" onClick={uploadDocument} disabled={uploading}>
            {uploading ? "Processing…" : "Choose File"}
          </Button>
          <p className="hint small">Supports PDF, DOCX, TXT, and Markdown.</p>
        </div>
        {error && <p className="error">{error}</p>}
      </Card>

      <Card
        title="Documents"
        actions={
          kbStatus && (
            <Badge tone={kbStatus.status === "READY" ? "success" : "warning"}>
              {kbStatus.status === "READY" ? "Ready" : "Processing"}
            </Badge>
          )
        }
      >
        {documents.length === 0 ? (
          <EmptyState
            icon="🗂️"
            title="No knowledge added yet"
            description="Upload a document so this agent can use it when answering."
          />
        ) : (
          <ul className="document-list">
            {documents.map((doc) => (
              <li key={doc.document_id} className="document-list-item">
                <div className="document-list-item-main">
                  <StatusDot tone={DOC_STATUS_TONE[doc.status] ?? "neutral"} />
                  <span className="document-filename">{doc.filename}</span>
                </div>
                <div className="document-list-item-meta">
                  {doc.status === "ERROR" && <span className="error-text">{doc.error_message}</span>}
                  <span>{formatBytes(doc.file_size)}</span>
                  <button className="link-button" onClick={() => removeDocument(doc.document_id)}>
                    Remove
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
        {documents.length > 0 && (
          <div className="kb-actions">
            <Button variant="secondary" onClick={clearAll}>
              Remove All Documents
            </Button>
          </div>
        )}
      </Card>
    </div>
  );
}
