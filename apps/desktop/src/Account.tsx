import { useCallback, useEffect, useState } from "react";
import { invoke } from "@tauri-apps/api/core";
import { Button } from "./ui";

interface SessionInfo {
  userId: string;
  email: string | null;
}

type SignUpResult =
  | { status: "signedIn"; session: SessionInfo }
  | { status: "confirmationRequired" };

/// Smallbird Cloud account panel: sign in/up against Supabase Auth (via the Rust
/// `auth` module), or sign out. Cloud sync is entirely opt-in — everything
/// else in the app works fully offline with no account at all, so this is
/// deliberately just a small settings-style panel, not a gate the user has
/// to pass to use the product.
export function Account({ onClose }: { onClose: () => void }) {
  const [cloudConfigured, setCloudConfigured] = useState<boolean | null>(null);
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [mode, setMode] = useState<"SIGN_IN" | "SIGN_UP">("SIGN_IN");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [syncStatus, setSyncStatus] = useState<string | null>(null);
  const [confirmationPending, setConfirmationPending] = useState(false);

  useEffect(() => {
    invoke<boolean>("auth_cloud_configured").then(setCloudConfigured).catch(() => setCloudConfigured(false));
    invoke<SessionInfo | null>("auth_get_session").then(setSession).catch(() => setSession(null));
  }, []);

  const runSync = useCallback(async () => {
    try {
      const mergedCount = await invoke<number>("sync_agents_now");
      setSyncStatus(mergedCount > 0 ? `Synced — ${mergedCount} agent(s) updated from the cloud.` : "Synced.");
    } catch (err) {
      setSyncStatus(`Sync failed: ${String(err)}`);
    }
  }, []);

  const handleSubmit = useCallback(async () => {
    setBusy(true);
    setError(null);
    setConfirmationPending(false);
    try {
      if (mode === "SIGN_IN") {
        const info = await invoke<SessionInfo>("auth_sign_in", { email, password });
        setSession(info);
        setPassword("");
        await runSync();
        return;
      }
      const result = await invoke<SignUpResult>("auth_sign_up", { email, password });
      if (result.status === "signedIn") {
        setSession(result.session);
        setPassword("");
        await runSync();
      } else {
        // "Confirm email" is enabled on this Supabase project — the account
        // was created but has no session until the user clicks the link.
        setConfirmationPending(true);
        setPassword("");
      }
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }, [mode, email, password, runSync]);

  const handleSignOut = useCallback(async () => {
    setBusy(true);
    try {
      await invoke("auth_sign_out");
      setSession(null);
      setSyncStatus(null);
    } finally {
      setBusy(false);
    }
  }, []);

  return (
    <div
      className="popover-overlay"
      onMouseDown={(e) => e.target === e.currentTarget && !busy && onClose()}
    >
      <div className="popover" role="dialog" aria-modal="true" aria-label="Account">
        <div className="popover-header">
          <span className="setup-section-label">Account</span>
          <button className="modal-close-btn" onClick={onClose} title="Close" aria-label="Close">
            ✕
          </button>
        </div>

        <div className="popover-body">
          {cloudConfigured === false && (
            <p className="setup-hint">
              Smallbird Cloud isn't configured on this build. Custom Agents and everything else keep
              working fully offline; sign-in and cloud sync will appear once this build is connected
              to Smallbird Cloud.
            </p>
          )}

          {cloudConfigured && session && (
            <>
              <p>
                Signed in as <strong>{session.email ?? session.userId}</strong>
              </p>
              <p className="setup-hint">
                Your Custom Agents sync to Smallbird Cloud so they survive a reinstall. Everything else
                (transcripts, recordings) stays local on this device.
              </p>
              {syncStatus && <p className="setup-hint">{syncStatus}</p>}
            </>
          )}

          {cloudConfigured && !session && (
            <>
              <div className="agent-mode-toggle">
                <button
                  className={`agent-mode-tab${mode === "SIGN_IN" ? " active" : ""}`}
                  onClick={() => {
                    setMode("SIGN_IN");
                    setConfirmationPending(false);
                    setError(null);
                  }}
                >
                  Sign in
                </button>
                <button
                  className={`agent-mode-tab${mode === "SIGN_UP" ? " active" : ""}`}
                  onClick={() => {
                    setMode("SIGN_UP");
                    setConfirmationPending(false);
                    setError(null);
                  }}
                >
                  Create account
                </button>
              </div>
              {confirmationPending && (
                <p className="setup-hint">
                  Account created. Check your email for a confirmation link, then sign in once
                  you've confirmed.
                </p>
              )}
              <div className="setup-identity-field">
                <input
                  className="setup-input"
                  type="email"
                  aria-label="Email"
                  placeholder="Email"
                  value={email}
                  onChange={(e) => setEmail(e.target.value)}
                />
              </div>
              <div className="setup-identity-field">
                <input
                  className="setup-input"
                  type="password"
                  aria-label="Password"
                  placeholder="Password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </div>
              {error && <p className="error">{error}</p>}
              <p className="setup-hint">Signing in is optional — Smallbird works fully offline without an account.</p>
            </>
          )}

          <div className="popover-footer">
            {cloudConfigured && session ? (
              <>
                <Button variant="ghost" onClick={handleSignOut} disabled={busy}>
                  Sign out
                </Button>
                <Button variant="secondary" onClick={runSync} disabled={busy}>
                  Sync now
                </Button>
              </>
            ) : cloudConfigured ? (
              <>
                <Button variant="ghost" onClick={onClose} disabled={busy}>
                  Cancel
                </Button>
                <Button variant="primary" onClick={handleSubmit} disabled={busy || !email || !password}>
                  {busy ? "Working…" : mode === "SIGN_IN" ? "Sign in" : "Create account"}
                </Button>
              </>
            ) : (
              <Button variant="ghost" onClick={onClose}>
                Close
              </Button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
