use std::io::{BufRead, BufReader, Write};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc::Sender;
use std::thread::JoinHandle;

use crate::audio::AudioSource;

use super::events::{SidecarLine, SttEvent, SttEventKind};

/// Locates a working Python 3 interpreter. Tries `py -3` first (the standard Windows
/// launcher, which resolves correctly even when bare `python`/`python3` are shadowed
/// by the Microsoft Store app-execution-alias stub — see docs/architecture.md), then
/// falls back to `python`.
fn find_python() -> Option<(String, Vec<String>)> {
    if Command::new("py")
        .args(["-3", "--version"])
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
    {
        return Some(("py".to_string(), vec!["-3".to_string()]));
    }
    if Command::new("python")
        .arg("--version")
        .stdout(Stdio::null())
        .stderr(Stdio::null())
        .status()
        .map(|s| s.success())
        .unwrap_or(false)
    {
        return Some(("python".to_string(), vec![]));
    }
    None
}

fn stt_package_dir() -> std::path::PathBuf {
    // In dev, CARGO_MANIFEST_DIR is apps/desktop/src-tauri; packages/stt sits
    // three levels up at the repo root.
    std::path::PathBuf::from(env!("CARGO_MANIFEST_DIR"))
        .join("..")
        .join("..")
        .join("..")
        .join("packages")
        .join("stt")
}

/// Which local engine the sidecar should run.
///
/// `StreamingAsr` (sherpa-onnx / NeMo FastConformer 80ms) is the production
/// engine as of the benchmark in `docs/stt-benchmark.md`. PocketSphinx is kept
/// reachable via `STT_ENGINE=pocketsphinx` so the two can be compared on the
/// same machine without a rebuild, and so there is a fallback if the streaming
/// venv is ever missing.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SttEngineKind {
    StreamingAsr,
    PocketSphinx,
}

impl SttEngineKind {
    fn from_env() -> Self {
        match std::env::var("STT_ENGINE").unwrap_or_default().trim().to_ascii_lowercase().as_str() {
            "pocketsphinx" | "sphinx" => Self::PocketSphinx,
            _ => Self::StreamingAsr,
        }
    }

    fn script_path(self) -> std::path::PathBuf {
        let base = stt_package_dir();
        match self {
            Self::StreamingAsr => base.join("streaming_asr_sidecar").join("sidecar.py"),
            Self::PocketSphinx => base.join("pocketsphinx_sidecar").join("sidecar.py"),
        }
    }
}

/// The STT sidecar's own virtualenv interpreter. sherpa-onnx and its ONNX
/// Runtime dependency are heavy enough to deserve isolation, mirroring how
/// `packages/rag` and `apps/backend` each own a venv rather than sharing one.
fn stt_venv_python() -> Option<std::path::PathBuf> {
    let candidate = stt_package_dir()
        .join(".venv")
        .join("Scripts")
        .join("python.exe");
    candidate.exists().then_some(candidate)
}

/// A running PocketSphinx sidecar process for one audio source (system audio or
/// microphone). Owns the child process and the threads that pump audio in / read
/// transcript events out.
pub struct SttSidecar {
    child: Child,
    stdin: Option<ChildStdin>,
    reader_thread: Option<JoinHandle<()>>,
}

impl SttSidecar {
    /// Spawns the sidecar process. `events_tx` receives every partial/final/error
    /// event the sidecar produces, forwarded from a dedicated reader thread so that
    /// writing audio to stdin never blocks on draining stdout (a naive
    /// write-then-read pattern deadlocks on Windows once the pipe buffer fills —
    /// see docs/progress.md Step 4 for how this was diagnosed).
    pub fn spawn(source: AudioSource, events_tx: Sender<SttEvent>) -> Result<Self, String> {
        let engine = SttEngineKind::from_env();

        // The streaming engine needs its own venv (sherpa-onnx + onnxruntime);
        // PocketSphinx is installed against a system interpreter. Fall back to
        // a system interpreter for either, so a missing venv produces a clear
        // sidecar-level error rather than a silent failure to start.
        let (python, mut base_args) = match (engine, stt_venv_python()) {
            (SttEngineKind::StreamingAsr, Some(venv)) => {
                (venv.to_string_lossy().to_string(), Vec::new())
            }
            (SttEngineKind::StreamingAsr, None) => {
                return Err(
                    "STT venv not found at packages/stt/.venv — run: \
                     py -3 -m venv packages/stt/.venv && \
                     packages/stt/.venv/Scripts/python.exe -m pip install sherpa-onnx numpy"
                        .to_string(),
                )
            }
            (SttEngineKind::PocketSphinx, _) => find_python().ok_or_else(|| {
                "no Python 3 interpreter found (tried `py -3` and `python`)".to_string()
            })?,
        };

        let script = engine.script_path();
        if !script.exists() {
            return Err(format!("STT sidecar script not found at {}", script.display()));
        }

        let source_arg = match source {
            AudioSource::SystemAudio => "SYSTEM_AUDIO",
            AudioSource::Microphone => "MICROPHONE",
        };

        base_args.push(script.to_string_lossy().to_string());
        base_args.push(source_arg.to_string());

        // Trailing silence before the current utterance is finalized. Settable
        // via the launch environment so it can be tuned without a rebuild. The
        // two engines want different defaults, so each sidecar picks its own
        // when this is unset rather than having one value imposed here.
        let end_silence_ms = std::env::var("STT_END_SILENCE_MS").ok();

        let mut command = Command::new(&python);
        command.args(&base_args);
        if let Some(ms) = end_silence_ms {
            command.env("STT_END_SILENCE_MS", ms);
        }
        if let Ok(threads) = std::env::var("STT_NUM_THREADS") {
            command.env("STT_NUM_THREADS", threads);
        }
        if let Ok(dir) = std::env::var("STT_MODEL_DIR") {
            command.env("STT_MODEL_DIR", dir);
        }

        let mut child = command
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped())
            .spawn()
            .map_err(|e| format!("failed to spawn STT sidecar ({python}): {e}"))?;

        let stdin = child.stdin.take();
        let stdout = child
            .stdout
            .take()
            .ok_or_else(|| "sidecar stdout not captured".to_string())?;
        let stderr = child.stderr.take();

        if let Some(stderr) = stderr {
            std::thread::Builder::new()
                .name("stt-sidecar-stderr".into())
                .spawn(move || {
                    let reader = BufReader::new(stderr);
                    for line in reader.lines().map_while(Result::ok) {
                        log::warn!("[stt sidecar stderr] {line}");
                    }
                })
                .ok();
        }

        let reader_thread = std::thread::Builder::new()
            .name("stt-sidecar-reader".into())
            .spawn(move || {
                let reader = BufReader::new(stdout);
                for line in reader.lines().map_while(Result::ok) {
                    if line.trim().is_empty() {
                        continue;
                    }
                    match serde_json::from_str::<SidecarLine>(&line) {
                        Ok(SidecarLine::Ready) => {
                            log::info!("STT sidecar ready ({source_arg})");
                        }
                        Ok(SidecarLine::Partial { text, source }) => {
                            let _ = events_tx.send(SttEvent {
                                kind: SttEventKind::Partial,
                                text,
                                source,
                                start_time: None,
                                end_time: None,
                            });
                        }
                        Ok(SidecarLine::Final {
                            text,
                            source,
                            start_time,
                            end_time,
                        }) => {
                            let _ = events_tx.send(SttEvent {
                                kind: SttEventKind::Final,
                                text,
                                source,
                                start_time: Some(start_time),
                                end_time: Some(end_time),
                            });
                        }
                        Ok(SidecarLine::Error { message }) => {
                            log::error!("STT sidecar error: {message}");
                        }
                        Err(err) => {
                            log::warn!("unparseable STT sidecar line: {line} ({err})");
                        }
                    }
                }
            })
            .map_err(|e| e.to_string())?;

        Ok(Self {
            child,
            stdin,
            reader_thread: Some(reader_thread),
        })
    }

    /// Encodes f32 samples (range -1.0..1.0) as PCM16 and writes them to the
    /// sidecar's stdin using the length-prefixed frame protocol.
    pub fn send_samples(&mut self, samples: &[f32]) -> Result<(), String> {
        let Some(stdin) = self.stdin.as_mut() else {
            return Err("sidecar stdin already closed".into());
        };
        let mut bytes = Vec::with_capacity(samples.len() * 2);
        for &s in samples {
            let clamped = s.clamp(-1.0, 1.0);
            let sample_i16 = (clamped * i16::MAX as f32) as i16;
            bytes.extend_from_slice(&sample_i16.to_le_bytes());
        }
        write_frame(stdin, &bytes)
    }

    /// Sends the zero-length flush marker so the sidecar finalizes any in-progress
    /// utterance immediately (used when the user pauses/stops recording).
    pub fn flush(&mut self) -> Result<(), String> {
        let Some(stdin) = self.stdin.as_mut() else {
            return Err("sidecar stdin already closed".into());
        };
        write_frame(stdin, &[])
    }

    /// Closes stdin (signals end-of-stream) and waits for the process to exit.
    pub fn shutdown(mut self) {
        self.stdin.take();
        let _ = self.child.wait();
        if let Some(handle) = self.reader_thread.take() {
            let _ = handle.join();
        }
    }
}

impl Drop for SttSidecar {
    /// Safety net for paths that don't call `shutdown()` explicitly (a panic
    /// unwinding through this struct, or the struct simply being dropped early):
    /// without this, the child Python process would keep running as an orphan,
    /// since Windows does not kill child processes when their parent exits.
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

fn write_frame(stdin: &mut ChildStdin, payload: &[u8]) -> Result<(), String> {
    let len = payload.len() as u32;
    stdin.write_all(&len.to_le_bytes()).map_err(|e| e.to_string())?;
    if !payload.is_empty() {
        stdin.write_all(payload).map_err(|e| e.to_string())?;
    }
    stdin.flush().map_err(|e| e.to_string())?;
    Ok(())
}
