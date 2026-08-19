use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::time::Duration;

const RAG_PORT: u16 = 8100;

fn rag_package_dir() -> PathBuf {
    // In dev, CARGO_MANIFEST_DIR is apps/desktop/src-tauri; the RAG service
    // package lives at packages/rag relative to the repo root.
    let manifest_dir = PathBuf::from(env!("CARGO_MANIFEST_DIR"));
    manifest_dir.join("..").join("..").join("..").join("packages").join("rag")
}

/// Locates the RAG service's own virtualenv interpreter. It has much heavier
/// dependencies (torch, sentence-transformers) than the STT sidecar, so it
/// gets its own venv (`packages/rag/.venv`) rather than sharing one — this
/// mirrors how `apps/backend` has its own venv too.
fn rag_venv_python() -> Option<PathBuf> {
    let candidate = rag_package_dir().join(".venv").join("Scripts").join("python.exe");
    if candidate.exists() {
        Some(candidate)
    } else {
        None
    }
}

pub struct RagServiceHandle {
    child: Option<Child>,
}

impl RagServiceHandle {
    pub fn base_url() -> String {
        format!("http://127.0.0.1:{RAG_PORT}")
    }

    /// Spawns the RAG service as a child process. Returns `Ok(None)` (not an
    /// error) if the service's venv hasn't been set up — the caller can still
    /// run the rest of the app without document upload/RAG features available,
    /// rather than failing the whole app to launch.
    ///
    /// `embed_config`: hardware-tier-driven (`RAG_EMBED_BATCH_SIZE`,
    /// `RAG_TORCH_THREADS`), read once at spawn time — Python's `Settings`
    /// class (packages/rag/app/core/config.py) reads these at process
    /// startup and caches them, so applying a new value requires restarting
    /// this process (see `restart`), the same way `packages/rag`'s own
    /// embedding model is loaded once and reused for the process lifetime.
    pub fn spawn(embed_config: EmbedProcessConfig) -> Result<Option<Self>, String> {
        let Some(python) = rag_venv_python() else {
            log::warn!(
                "RAG service venv not found at packages/rag/.venv — document upload/RAG search will be unavailable"
            );
            return Ok(None);
        };

        let package_dir = rag_package_dir();

        let mut child = Command::new(&python)
            .args(["-m", "uvicorn", "app.main:app", "--port", &RAG_PORT.to_string()])
            .current_dir(&package_dir)
            .env("RAG_EMBED_BATCH_SIZE", embed_config.embed_batch_size.to_string())
            .env("RAG_TORCH_THREADS", embed_config.torch_threads.to_string())
            .stdin(Stdio::null())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|e| format!("failed to spawn RAG service: {e}"))?;

        forward_child_output(child.stdout.take(), "stdout");
        forward_child_output(child.stderr.take(), "stderr");

        Ok(Some(Self { child: Some(child) }))
    }

    pub fn shutdown(&mut self) {
        if let Some(mut child) = self.child.take() {
            let _ = child.kill();
            let _ = child.wait();
        }
    }

    /// Kills the current process and spawns a fresh one with new
    /// embedding-config env vars. Used when the user changes performance
    /// mode — RAG's Python settings are fixed at process startup (see
    /// `spawn`'s doc comment), so a live in-process reconfiguration isn't
    /// possible without a deeper change to how `packages/rag` caches
    /// settings. Callers should treat the brief gap between shutdown and
    /// the new process becoming healthy the same way initial startup is
    /// treated (poll `/health`), not as an error.
    pub fn restart(&mut self, embed_config: EmbedProcessConfig) -> Result<(), String> {
        self.shutdown();
        let Some(mut spawned) = Self::spawn(embed_config)? else {
            return Err("RAG service venv not found — cannot restart".to_string());
        };
        // `.take()`, not a whole-struct move — `spawned` still runs its
        // `Drop` impl at the end of this scope, which is a no-op once its
        // `child` has been taken (mirrors `shutdown()`'s own `self.child.take()`).
        self.child = spawned.child.take();
        Ok(())
    }
}

/// The subset of `hardware::PerformanceConfig` relevant to spawning the RAG
/// child process — kept as its own small struct (rather than passing the
/// full `PerformanceConfig` here) so `rag::process` does not need to depend
/// on the `hardware` module's other STT/retrieval fields it has no use for.
#[derive(Debug, Clone, Copy)]
pub struct EmbedProcessConfig {
    pub embed_batch_size: u32,
    pub torch_threads: u32,
}

impl Drop for RagServiceHandle {
    /// Same reasoning as `SttSidecar`'s Drop impl: without this, an unclean
    /// Rust-side exit would leave the RAG service (and the memory-heavy
    /// embedding model it has loaded) running as an orphaned process.
    fn drop(&mut self) {
        self.shutdown();
    }
}

/// Forwards a child process's stdout/stderr into the `log` crate on a
/// dedicated thread, the same pattern used for the STT sidecar's stderr
/// (`stt::sidecar`) — keeps RAG service logs visible in the desktop app's own
/// log output without blocking anything on the pipe being drained.
fn forward_child_output<R>(pipe: Option<R>, label: &'static str)
where
    R: std::io::Read + Send + 'static,
{
    let Some(pipe) = pipe else { return };
    std::thread::Builder::new()
        .name(format!("rag-service-{label}"))
        .spawn(move || {
            use std::io::{BufRead, BufReader};
            let reader = BufReader::new(pipe);
            for line in reader.lines().map_while(Result::ok) {
                log::info!("[rag service {label}] {line}");
            }
        })
        .ok();
}

/// Polls the RAG service's `/health` endpoint until it responds or the timeout
/// elapses. Called once after spawning, before the app reports the service as
/// available.
pub fn wait_until_healthy(timeout: Duration) -> bool {
    let deadline = std::time::Instant::now() + timeout;
    let url = format!("{}/health", RagServiceHandle::base_url());
    while std::time::Instant::now() < deadline {
        if let Ok(response) = reqwest::blocking::get(&url) {
            if response.status().is_success() {
                return true;
            }
        }
        std::thread::sleep(Duration::from_millis(300));
    }
    false
}

/// The embedding model can take a while to load on first request (see
/// docs/progress.md Step 9 — ~35s cold, cached after) plus uvicorn's own
/// startup, so this uses a generous timeout; a `false` return just means the
/// RAG service commands will report "unavailable" until it does come up.
pub fn wait_until_healthy_default() -> bool {
    wait_until_healthy(Duration::from_secs(60))
}
