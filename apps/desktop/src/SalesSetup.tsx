import { useCallback, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { open } from "@tauri-apps/plugin-dialog";
import { readFile } from "@tauri-apps/plugin-fs";
import { Button } from "./ui";

type CallStage = "discovery" | "demo" | "negotiation" | "closing";

const STAGES: { value: CallStage; label: string }[] = [
  { value: "discovery", label: "Discovery" },
  { value: "demo", label: "Demo" },
  { value: "negotiation", label: "Negotiation" },
  { value: "closing", label: "Closing" },
];

interface Props {
  onStart: () => void;
}

export function SalesSetup({ onStart }: Props) {
  const [customerName, setCustomerName] = useState("");
  const [companyName, setCompanyName] = useState("");
  const [callStage, setCallStage] = useState<CallStage>("discovery");
  const [fileName, setFileName] = useState<string | null>(null);
  const [fileBytes, setFileBytes] = useState<number[] | null>(null);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);

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

  const startCall = useCallback(async () => {
    setError(null);
    setStarting(true);
    try {
      // Persist for the overlay window (separate JS context) to read on mount.
      window.localStorage.setItem(
        "sales-mode:active-call",
        JSON.stringify({ customerName: customerName.trim(), companyName: companyName.trim(), callStage }),
      );

      if (fileBytes && fileName) {
        invoke("upload_document", {
          filename: fileName,
          bytes: fileBytes,
          documentType: "OTHER",
        }).catch((e) => console.error("Failed to upload sales document:", e));
      }

      await invoke("clear_sales_session").catch(() => {});
      await invoke("start_system_audio_capture").catch((e) => {
        if (String(e) !== "capture already running") throw e;
      });
      await invoke("show_sales_overlay");
      onStart();
    } catch (e) {
      setError(String(e));
    } finally {
      setStarting(false);
    }
  }, [customerName, companyName, callStage, fileBytes, fileName, onStart]);

  return (
    <div className="setup-shell">
      <section className="setup-hero">
        <div className="setup-hero-text">
          <h1 className="setup-title">New Sales Call</h1>
          <p className="setup-subtitle">Set up context, then start your call</p>
        </div>
        <div className="setup-hero-actions">
          <Button variant="primary" onClick={startCall} disabled={starting}>
            {starting ? "Starting…" : "Start Call"}
          </Button>
        </div>
      </section>

      {error && <p className="error">{error}</p>}

      <div className="setup-identity">
        <div className="setup-identity-field">
          <label htmlFor="sales-customer">Customer Name</label>
          <input
            id="sales-customer"
            className="setup-input"
            value={customerName}
            onChange={(e) => setCustomerName(e.target.value)}
            placeholder="e.g. Jamie Rivera"
          />
        </div>
        <div className="setup-identity-field">
          <label htmlFor="sales-company">Company</label>
          <input
            id="sales-company"
            className="setup-input"
            value={companyName}
            onChange={(e) => setCompanyName(e.target.value)}
            placeholder="e.g. Acme Inc."
          />
        </div>
      </div>

      <div className="setup-identity">
        <div className="setup-identity-field">
          <label htmlFor="sales-stage">Call Stage</label>
          <select
            id="sales-stage"
            className="setup-input"
            value={callStage}
            onChange={(e) => setCallStage(e.target.value as CallStage)}
          >
            {STAGES.map((s) => (
              <option key={s.value} value={s.value}>
                {s.label}
              </option>
            ))}
          </select>
        </div>
      </div>

      <div className="setup-section" style={{ maxWidth: 420 }}>
        <div className="setup-section-head">
          <span className="setup-section-label">Product / Pricing Document</span>
          <span className="setup-section-optional">Optional</span>
        </div>
        <div className="setup-section-body">
          {fileName ? (
            <div className="setup-file-chip">
              <span className="setup-file-name">{fileName}</span>
              <button className="link-button" onClick={clearFile}>
                Remove
              </button>
            </div>
          ) : (
            <Button variant="secondary" size="sm" onClick={pickFile}>
              Upload a file
            </Button>
          )}
        </div>
      </div>
    </div>
  );
}
