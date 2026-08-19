import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import { readFile } from "@tauri-apps/plugin-fs";
import type { DocumentMetadata, DocumentType, KnowledgeBaseStatus } from "./types";
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

const DOCUMENT_TYPES: { value: DocumentType; label: string }[] = [
  { value: "RESUME", label: "Resume" },
  { value: "JOB_DESCRIPTION", label: "Job Description" },
  { value: "PROJECT", label: "Project" },
  { value: "COMPANY", label: "Company Info" },
  { value: "INTERVIEW_PREPARATION", label: "Interview Prep Notes" },
  { value: "TECHNICAL_NOTES", label: "Technical Notes" },
  { value: "OTHER", label: "Other" },
];

function formatBytes(bytes: number) {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}

interface Props {
  role: string;
  onRoleChange: (value: string) => void;
  company: string;
  onCompanyChange: (value: string) => void;
}

export function Preparation({ role, onRoleChange, company, onCompanyChange }: Props) {
  const [ragAvailable, setRagAvailable] = useState<boolean | null>(null);
  const [documents, setDocuments] = useState<DocumentMetadata[]>([]);
  const [kbStatus, setKbStatus] = useState<KnowledgeBaseStatus | null>(null);
  const [uploadType, setUploadType] = useState<DocumentType>("RESUME");
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    try {
      const available = await invoke<boolean>("check_rag_connection");
      setRagAvailable(available);
      if (!available) return;
      const [docs, status] = await Promise.all([
        invoke<DocumentMetadata[]>("list_documents"),
        invoke<KnowledgeBaseStatus>("knowledge_base_status"),
      ]);
      setDocuments(docs);
      setKbStatus(status);
    } catch (e) {
      setRagAvailable(false);
    }
  }, []);

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
        filters: [
          { name: "Documents", extensions: ["pdf", "docx", "txt", "md", "markdown"] },
        ],
      });
      if (!selected || Array.isArray(selected)) return;

      setUploading(true);
      const bytes = await readFile(selected);
      const filename = selected.split(/[\\/]/).pop() ?? "document";

      await invoke("upload_document", {
        filename,
        bytes: Array.from(bytes),
        documentType: uploadType,
      });
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setUploading(false);
    }
  }, [uploadType, refresh]);

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

  const rebuildKnowledgeBase = useCallback(async () => {
    setError(null);
    try {
      await invoke("clear_knowledge_base");
      await refresh();
    } catch (e) {
      setError(String(e));
    }
  }, [refresh]);

  if (ragAvailable === false) {
    return (
      <div className="prep-panel">
        <Card>
          <EmptyState
            icon="⚠️"
            title="Document tools aren't available right now"
            description="Try again in a moment. You can still record and analyze your interview without them."
          />
        </Card>
      </div>
    );
  }

  return (
    <div className="prep-panel">
      <Card title="Interview Preparation">
        <div className="prep-fields-row">
          <div className="prep-field">
            <label htmlFor="role">Role</label>
            <input
              id="role"
              value={role}
              onChange={(e) => onRoleChange(e.target.value)}
              placeholder="AI/ML Engineer"
            />
          </div>
          <div className="prep-field">
            <label htmlFor="company">Company</label>
            <input
              id="company"
              value={company}
              onChange={(e) => onCompanyChange(e.target.value)}
              placeholder="Example Company"
            />
          </div>
        </div>
      </Card>

      <Card title="Upload Document">
        <div className="upload-dropzone">
          <span className="upload-dropzone-icon">📄</span>
          <div className="upload-row">
            <select value={uploadType} onChange={(e) => setUploadType(e.target.value as DocumentType)}>
              {DOCUMENT_TYPES.map((t) => (
                <option key={t.value} value={t.value}>
                  {t.label}
                </option>
              ))}
            </select>
            <Button variant="primary" onClick={uploadDocument} disabled={uploading}>
              {uploading ? "Processing…" : "Choose File"}
            </Button>
          </div>
          <p className="hint small">Supports PDF, DOCX, TXT, and Markdown.</p>
        </div>
        {error && <p className="error">{error}</p>}
      </Card>

      <Card
        title="Your Documents"
        actions={
          kbStatus && (
            <Badge tone={kbStatus.status === "READY" ? "success" : "warning"}>
              {kbStatus.status === "READY" ? "Ready" : "Processing"}
            </Badge>
          )
        }
      >
        {kbStatus && kbStatus.document_count > 0 && (
          <div className="kb-stats">
            <span className="kb-stat-pill">
              <strong>{kbStatus.document_count}</strong> document{kbStatus.document_count === 1 ? "" : "s"}
            </span>
          </div>
        )}
        {documents.length === 0 ? (
          <EmptyState icon="🗂️" title="No documents uploaded yet" description="Upload a resume or job description above so WhitedotAI can tailor its help to you." />
        ) : (
          <ul className="document-list">
            {documents.map((doc) => (
              <li key={doc.document_id} className="document-list-item">
                <div className="document-list-item-main">
                  <StatusDot tone={DOC_STATUS_TONE[doc.status] ?? "neutral"} />
                  <span className="document-filename">{doc.filename}</span>
                  <span className="document-type-tag">{doc.document_type}</span>
                </div>
                <div className="document-list-item-meta">
                  {doc.status === "ERROR" && (
                    <span className="error-text">{doc.error_message}</span>
                  )}
                  <span>{formatBytes(doc.file_size)}</span>
                  <button className="link-button" onClick={() => removeDocument(doc.document_id)}>
                    Remove
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
        <div className="kb-actions">
          <Button variant="secondary" onClick={rebuildKnowledgeBase} disabled={documents.length === 0}>
            Remove All Documents
          </Button>
        </div>
      </Card>
    </div>
  );
}
