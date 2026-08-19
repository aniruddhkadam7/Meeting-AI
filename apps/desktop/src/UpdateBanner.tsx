import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { Button } from "./ui";

interface UpdateInfo {
  version: string;
  notes: string | null;
}

/// Checks for an update once on launch and shows a small dismissible banner
/// if one is available. Installing is always an explicit user action (click
/// "Update now") — WhitedotAI never silently restarts itself mid-session.
export function UpdateBanner() {
  const [update, setUpdate] = useState<UpdateInfo | null>(null);
  const [installing, setInstalling] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    invoke<UpdateInfo | null>("check_for_update")
      .then(setUpdate)
      .catch(() => {
        // No update endpoint configured, or offline — stay silent, this is
        // a background convenience check, not a user-facing action.
      });
  }, []);

  const install = useCallback(async () => {
    setInstalling(true);
    setError(null);
    try {
      await invoke("install_update_and_restart");
    } catch (err) {
      setError(String(err));
      setInstalling(false);
    }
  }, []);

  if (!update || dismissed) return null;

  return (
    <div className="update-banner">
      <span>
        WhitedotAI {update.version} is available.
        {error && <span className="update-banner-error"> {error}</span>}
      </span>
      <div className="update-banner-actions">
        <Button variant="primary" size="sm" onClick={install} disabled={installing}>
          {installing ? "Updating…" : "Update now"}
        </Button>
        <Button variant="ghost" size="sm" onClick={() => setDismissed(true)} disabled={installing}>
          Later
        </Button>
      </div>
    </div>
  );
}
