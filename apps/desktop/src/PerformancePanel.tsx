import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { Button } from "./ui";

interface HardwareProfile {
  cpuPhysicalCores: number;
  cpuLogicalCores: number;
  cpuBrand: string;
  totalRamMb: number;
  availableRamMb: number;
  gpuVendor: string | null;
  gpuName: string | null;
  gpuVramMb: number | null;
  storageIsSsd: boolean | null;
  windowsVersion: string;
}

type HardwareTier = "entry" | "standard" | "performance" | "highPerformance";
type PerformanceMode = "adaptive" | "maximumPerformance" | "batterySaver";

interface PerformanceConfig {
  sttNumThreads: number;
  ragTopK: number;
  ragMaxContextChars: number;
  ragSimilarityThreshold: number;
  ragRetrievalTimeoutMs: number;
  ragEmbedBatchSize: number;
  ragTorchThreads: number;
}

interface PerformanceModeInfo {
  mode: PerformanceMode;
  detectedTier: HardwareTier;
  effectiveConfig: PerformanceConfig;
}

const TIER_LABELS: Record<HardwareTier, string> = {
  entry: "Entry",
  standard: "Standard",
  performance: "Performance",
  highPerformance: "High Performance",
};

const MODE_OPTIONS: { value: PerformanceMode; label: string; description: string }[] = [
  {
    value: "adaptive",
    label: "Adaptive",
    description: "Automatically tuned for your hardware. Recommended.",
  },
  {
    value: "maximumPerformance",
    label: "Maximum Performance",
    description: "Best accuracy and context. Uses more CPU and memory.",
  },
  {
    value: "batterySaver",
    label: "Battery Saver",
    description: "Lighter on CPU and memory — smoother on modest hardware.",
  },
];

function formatGpu(profile: HardwareProfile): string {
  if (!profile.gpuName) {
    return "No dedicated graphics card detected — that's fine, REDLY doesn't require one.";
  }
  const vram = profile.gpuVramMb ? `, ${Math.round(profile.gpuVramMb / 1024)}GB` : "";
  return `${profile.gpuName}${vram}`;
}

function formatStorage(profile: HardwareProfile): string | null {
  if (profile.storageIsSsd === null) return null;
  return profile.storageIsSsd ? "SSD" : "HDD";
}

/// REDLY Performance panel: shows the machine's detected hardware and lets
/// the user pick Adaptive (default)/Maximum Performance/Battery Saver.
/// Mirrors Account.tsx's modal shell/state conventions — local useState
/// only, typed invoke<T> calls, busy/error handling around the one write
/// action (set_performance_mode).
export function PerformancePanel({ onClose }: { onClose: () => void }) {
  const [profile, setProfile] = useState<HardwareProfile | null>(null);
  const [modeInfo, setModeInfo] = useState<PerformanceModeInfo | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showAdvanced, setShowAdvanced] = useState(false);

  useEffect(() => {
    invoke<HardwareProfile>("get_hardware_profile").then(setProfile).catch((err) => setError(String(err)));
    invoke<PerformanceModeInfo>("get_performance_mode").then(setModeInfo).catch((err) => setError(String(err)));
  }, []);

  const handleSelectMode = useCallback(async (mode: PerformanceMode) => {
    setBusy(true);
    setError(null);
    try {
      await invoke("set_performance_mode", { mode });
      const info = await invoke<PerformanceModeInfo>("get_performance_mode");
      setModeInfo(info);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }, []);

  return (
    <div className="modal-backdrop" onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()}>
      <div className="modal-panel" role="dialog" aria-modal="true" aria-label="REDLY Performance">
        <header className="modal-header">
          <h1 className="setup-title">REDLY Performance</h1>
          <button className="modal-close-btn" onClick={onClose} title="Close" aria-label="Close">
            ✕
          </button>
        </header>

        <div className="modal-body">
          {error && <p className="error">{error}</p>}

          {profile && (
            <>
              <p className="setup-hint">Hardware detected on this device:</p>
              <p>
                {profile.cpuLogicalCores} CPU cores
                {profile.cpuBrand ? ` (${profile.cpuBrand})` : ""}
              </p>
              <p>{Math.round(profile.totalRamMb / 1024)} GB memory</p>
              <p>{formatGpu(profile)}</p>
              {formatStorage(profile) && <p className="setup-hint">Storage: {formatStorage(profile)}</p>}
            </>
          )}

          {modeInfo && (
            <p className="setup-hint">
              Your hardware: <strong>{TIER_LABELS[modeInfo.detectedTier]}</strong>
            </p>
          )}

          <div className="agent-mode-toggle">
            {MODE_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                className={`agent-mode-tab${modeInfo?.mode === opt.value ? " active" : ""}`}
                onClick={() => handleSelectMode(opt.value)}
                disabled={busy}
              >
                {opt.label}
              </button>
            ))}
          </div>
          {modeInfo && (
            <p className="setup-hint">{MODE_OPTIONS.find((o) => o.value === modeInfo.mode)?.description}</p>
          )}

          {modeInfo && (
            <>
              <button className="link-button" onClick={() => setShowAdvanced((v) => !v)}>
                {showAdvanced ? "Hide" : "Show"} advanced details
              </button>
              {showAdvanced && (
                <ul className="setup-hint">
                  <li>STT threads: {modeInfo.effectiveConfig.sttNumThreads}</li>
                  <li>RAG top-K: {modeInfo.effectiveConfig.ragTopK}</li>
                  <li>RAG context budget: {modeInfo.effectiveConfig.ragMaxContextChars} chars</li>
                  <li>RAG retrieval timeout: {modeInfo.effectiveConfig.ragRetrievalTimeoutMs}ms</li>
                </ul>
              )}
            </>
          )}
        </div>

        <footer className="modal-footer">
          <Button variant="ghost" onClick={onClose} disabled={busy}>
            Close
          </Button>
        </footer>
      </div>
    </div>
  );
}
