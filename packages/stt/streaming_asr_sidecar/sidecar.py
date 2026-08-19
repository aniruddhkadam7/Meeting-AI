"""Local streaming ASR sidecar (sherpa-onnx / NVIDIA NeMo FastConformer).

Replaces the PocketSphinx sidecar. Speaks the **same wire protocol**:

    stdin :  [u32 len LE][len bytes PCM16 mono @16kHz] ...
             A zero-length frame means "flush / finalize now".
    stdout:  one JSON object per line
             {"type":"ready"}
             {"type":"partial","text":"...","source":"SYSTEM_AUDIO"}
             {"type":"final","text":"...","source":"SYSTEM_AUDIO",
              "start_time":12.34,"end_time":13.02}
             {"type":"error","message":"..."}

Why this engine: it is a *native streaming transducer*. Partial hypotheses are
what the decoder actually believes at that moment, so they only ever extend —
unlike a rolling-window approach over an offline model (whisper, Moonshine),
where each re-decode is independent and earlier words visibly rewrite
themselves. Benchmark numbers and the alternatives considered are in
`docs/stt-benchmark.md`.

Threading: decoding runs on a worker thread and stdin reading stays on the main
thread, so a slow decode can never stall audio intake. Audio is queued, never
dropped.

The model is loaded **once** at startup and kept resident for the life of the
process. Between utterances the decoder state is reset with
`recognizer.reset(stream)`, which is a cheap state clear — the ~130 MB of
weights are never reloaded.
"""

from __future__ import annotations

import json
import logging
import os
import queue
import struct
import sys
import threading
import time
from pathlib import Path

import numpy as np

from vad import EnergyVad, UtteranceGate, VadConfig

# stdout is the wire protocol (one JSON object per line) and must never carry
# anything else — diagnostic logging goes to stderr instead, which
# apps/desktop/src-tauri/src/stt/sidecar.rs already reads and forwards to
# Rust's `log::warn!`, visible in the `npm run tauri dev` console. Without
# this basicConfig call, module-level `logging.getLogger(...).info(...)` calls
# are silently dropped (no handler attached to the root logger by default).
logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(name)s: %(message)s")

# Trailing silence, in seconds, before an utterance is finalized. This is the
# dominant term in "how long after the interviewer stops talking does the
# question settle", and the product budget for that is under 1s end to end.
# 0.6s leaves room for the ~200ms the decoder itself needs while staying well
# inside the budget. Overridable for tuning without a rebuild.
DEFAULT_END_SILENCE_MS = 600
MIN_END_SILENCE_MS = 200
MAX_END_SILENCE_MS = 2000

# Trailing silence before finalizing when nothing has been decoded yet. Longer,
# because there is no pending text to lose and firing early just churns.
SILENCE_NO_TEXT_S = 2.0

# ONNX Runtime threads. Measured at 4: more threads did not reduce latency and
# spent noticeably more CPU spinning, which matters on a normal laptop.
DEFAULT_NUM_THREADS = 4

# VAD gate: skips decode_stream() (the expensive FastConformer forward pass)
# during confirmed silence. Does NOT skip accept_waveform() — audio is always
# buffered — and does NOT participate in endpointing in any way; sherpa-onnx's
# own rule1/rule2/rule3 (see build_recognizer) are the sole authority on when
# an utterance ends. Overridable for tuning without a rebuild, same pattern
# as every other sidecar knob. See docs/stt-performance-phase2.md for the
# benchmark evidence behind this being worth doing.
DEFAULT_VAD_ENABLED = True
DEFAULT_VAD_HANGOVER_MS = 700



class _Flush:
    """Queue sentinel for "finalize now".

    A distinct object rather than a string: queue items are numpy arrays, and
    `array == "FLUSH"` is an elementwise comparison whose truth value raises.
    """


FLUSH = _Flush()
SHUTDOWN = None


def emit(obj: dict) -> None:
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def read_exact(stream, n: int) -> bytes | None:
    buf = bytearray()
    while len(buf) < n:
        chunk = stream.read(n - len(buf))
        if not chunk:
            return None
        buf.extend(chunk)
    return bytes(buf)


def _env_int(name: str, default: int, low: int, high: int) -> int:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return default
    try:
        return max(low, min(high, int(raw)))
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name, "").strip().lower()
    if not raw:
        return default
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return default


def _resolve_model_dir() -> Path:
    """Model location, overridable via `STT_MODEL_DIR`. Resolved relative to
    this file so it works the same whether launched from the repo root or from
    the Tauri dev server's working directory."""
    override = os.environ.get("STT_MODEL_DIR", "").strip()
    if override:
        return Path(override)
    return (
        Path(__file__).resolve().parents[3]
        / "models"
        / "stt"
        / "nemo-fastconformer-80ms-int8"
    )


def _find(model_dir: Path, *patterns: str) -> Path:
    for pattern in patterns:
        matches = sorted(model_dir.glob(pattern))
        if matches:
            return matches[0]
    raise FileNotFoundError(
        f"none of {patterns} in {model_dir} "
        f"(contents: {[p.name for p in model_dir.iterdir()] if model_dir.is_dir() else 'MISSING'})"
    )


def build_recognizer(model_dir: Path, end_silence_s: float, num_threads: int):
    import sherpa_onnx

    return sherpa_onnx.OnlineRecognizer.from_transducer(
        tokens=str(_find(model_dir, "tokens.txt")),
        encoder=str(_find(model_dir, "encoder*.onnx")),
        decoder=str(_find(model_dir, "decoder*.onnx")),
        joiner=str(_find(model_dir, "joiner*.onnx")),
        num_threads=num_threads,
        sample_rate=16000,
        feature_dim=80,
        decoding_method="greedy_search",
        enable_endpoint_detection=True,
        rule1_min_trailing_silence=SILENCE_NO_TEXT_S,
        rule2_min_trailing_silence=end_silence_s,
        # Effectively disable the "utterance got too long" rule. Cutting a
        # question in half mid-sentence because it ran past a timer is worse
        # than a long segment; silence-based endpointing handles real
        # boundaries.
        rule3_min_utterance_length=300.0,
        provider="cpu",
    )


def main() -> int:
    source = sys.argv[1] if len(sys.argv) > 1 else "SYSTEM_AUDIO"
    end_silence_s = (
        _env_int("STT_END_SILENCE_MS", DEFAULT_END_SILENCE_MS, MIN_END_SILENCE_MS, MAX_END_SILENCE_MS)
        / 1000.0
    )
    num_threads = _env_int("STT_NUM_THREADS", DEFAULT_NUM_THREADS, 1, 16)
    vad_enabled = _env_bool("STT_VAD_GATE_ENABLED", DEFAULT_VAD_ENABLED)
    vad_hangover_ms = _env_int("STT_VAD_HANGOVER_MS", DEFAULT_VAD_HANGOVER_MS, 200, 5000)
    model_dir = _resolve_model_dir()

    if not model_dir.is_dir():
        emit({
            "type": "error",
            "message": (
                f"STT model not found at {model_dir}. "
                f"Run: py -3 packages/stt/scripts/install_model.py"
            ),
        })
        return 1

    try:
        recognizer = build_recognizer(model_dir, end_silence_s, num_threads)
        stream = recognizer.create_stream()
    except Exception as exc:  # noqa: BLE001
        emit({"type": "error", "message": f"failed to initialize recognizer: {exc}"})
        return 1

    emit({
        "type": "ready",
        "engine": "sherpa-onnx nemo-streaming-fast-conformer-80ms-int8",
        "end_silence_ms": int(end_silence_s * 1000),
        "num_threads": num_threads,
        "vad_gate_enabled": vad_enabled,
    })

    audio_q: queue.Queue = queue.Queue()
    # Guards `recognizer`/`stream`, which are touched by the worker and by the
    # flush path when a zero-length frame arrives.
    lock = threading.Lock()
    utterance_start = [None]
    # `hangover_ms` deliberately longer than `end_silence_s` (see vad.py's
    # VadConfig doc) so the VAD gate is never what decides an utterance is
    # over — it only ever defers decode_stream() calls during silence that
    # sherpa-onnx's own endpointer would also eventually call silence.
    gate = UtteranceGate(EnergyVad(VadConfig(hangover_ms=vad_hangover_ms))) if vad_enabled else None
    vad_skipped_frames = [0]
    vad_decoded_frames = [0]

    def worker() -> None:
        last_partial = ""
        while True:
            item = audio_q.get()
            if item is SHUTDOWN:
                break

            if item is FLUSH:
                # Explicit flush from Rust (pause/stop): finalize whatever is
                # pending so the last question is never left hanging. Never
                # gated by VAD — this is an explicit "finalize now" signal,
                # not a normal audio chunk, so it always fully decodes
                # whatever is buffered regardless of the gate's current
                # speech/silence read.
                with lock:
                    while recognizer.is_ready(stream):
                        recognizer.decode_stream(stream)
                    text = recognizer.get_result(stream).strip()
                    if text:
                        _emit_final(text)
                    recognizer.reset(stream)
                    if gate is not None:
                        gate.reset()
                    last_partial = ""
                continue

            samples = item
            if utterance_start[0] is None:
                utterance_start[0] = time.monotonic()

            with lock:
                stream.accept_waveform(16000, samples)

                # VAD gate (packages/stt/streaming_asr_sidecar/vad.py's
                # UtteranceGate): decide whether THIS chunk's audio is worth
                # the cost of decode_stream() at all. `accept_waveform` above
                # has already buffered the samples regardless of the gate's
                # decision — skipping decode never drops audio, only defers
                # it. See vad.py's module doc for the full correctness
                # rationale (in particular: why this only ever skips decode
                # BEFORE speech starts in an utterance, never during/after —
                # an earlier, more aggressive design regressed finalize
                # latency 353ms -> 2865ms by starving sherpa-onnx's own
                # endpointer of the decoded frames it needs to fire).
                should_decode = gate.observe(samples) if gate is not None else True
                if gate is not None:
                    if should_decode:
                        vad_decoded_frames[0] += 1
                    else:
                        vad_skipped_frames[0] += 1

                if should_decode:
                    while recognizer.is_ready(stream):
                        recognizer.decode_stream(stream)

                    if recognizer.is_endpoint(stream):
                        text = recognizer.get_result(stream).strip()
                        if text:
                            _emit_final(text)
                        recognizer.reset(stream)
                        if gate is not None:
                            gate.reset()
                        last_partial = ""
                        continue

                    text = recognizer.get_result(stream).strip()
                else:
                    text = last_partial

            if text and text != last_partial:
                emit({"type": "partial", "text": text, "source": source})
                last_partial = text

    def _emit_final(text: str) -> None:
        started = utterance_start[0] or time.monotonic()
        payload = {
            "type": "final",
            "text": text,
            "source": source,
            "start_time": started,
            "end_time": time.monotonic(),
        }
        emit(payload)
        utterance_start[0] = None

    worker_thread = threading.Thread(target=worker, name="asr-worker", daemon=True)
    worker_thread.start()

    stdin = sys.stdin.buffer
    try:
        while True:
            header = read_exact(stdin, 4)
            if header is None:
                break
            (length,) = struct.unpack("<I", header)
            if length == 0:
                audio_q.put(FLUSH)
                continue
            payload = read_exact(stdin, length)
            if payload is None:
                break
            samples = np.frombuffer(payload, dtype="<i2").astype(np.float32) / 32768.0
            audio_q.put(samples)
    except Exception as exc:  # noqa: BLE001
        emit({"type": "error", "message": str(exc)})
        return 1
    finally:
        audio_q.put(FLUSH)
        audio_q.put(SHUTDOWN)
        worker_thread.join(timeout=15.0)
        if vad_enabled:
            decoded, skipped = vad_decoded_frames[0], vad_skipped_frames[0]
            total = decoded + skipped
            skip_pct = (skipped / total * 100.0) if total else 0.0
            logging.getLogger("stt.vad").info(
                "gate summary: decoded=%d skipped=%d (%.1f%% of chunks skipped)",
                decoded, skipped, skip_pct,
            )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
