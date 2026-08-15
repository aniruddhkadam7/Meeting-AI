"""True-streaming transducer engines via sherpa-onnx.

Covers every candidate that ships a *native* streaming export — a stateful
encoder that consumes audio chunk by chunk and can be asked for its current
hypothesis at any moment:

  * streaming Zipformer transducer (English, Kroko 2025)
  * NVIDIA NeMo streaming FastConformer transducer (80 ms / 480 ms)
  * NVIDIA Parakeet unified EN 0.6B streaming export (240 ms / 560 ms)

This is architecturally what we actually want, and what PocketSphinx and
whisper.cpp are not: partial results fall out of the decoder for free rather
than being manufactured by re-running an offline model over a growing buffer.

Inference runs on a dedicated worker thread. `feed_audio` only enqueues, so it
returns in microseconds regardless of model size — this is the property that
keeps the Tauri UI thread free in the real application, and it is measured
(see `feed_block_ms_p99` in the results).
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass

import numpy as np

from .. import models
from .base import EngineInfo, EngineUnavailable, EventKind, STTEngine, SttEvent


@dataclass(frozen=True)
class StreamingConfig:
    model_key: str
    display_name: str
    #: Trailing silence (seconds) after decoded speech before the utterance is
    #: finalized. The spec's finalization budget is 300-800 ms, so the default
    #: sits inside it rather than at sherpa-onnx's much laggier 1.2 s default.
    endpoint_trailing_silence_s: float = 0.6
    #: Trailing silence before finalizing when nothing was decoded.
    endpoint_silence_no_text_s: float = 2.0
    num_threads: int = 4
    strategy: str = "native streaming transducer"
    notes: str = ""


class SherpaStreamingSTT(STTEngine):
    def __init__(self, config: StreamingConfig) -> None:
        super().__init__()
        self._config = config
        self._recognizer = None
        self._stream = None
        self._worker: threading.Thread | None = None
        self._audio_q: queue.Queue = queue.Queue()
        self._events_q: queue.Queue = queue.Queue()
        self._stop_flag = threading.Event()
        self._model_bytes = 0
        self._audio_time_s = 0.0

    @property
    def info(self) -> EngineInfo:
        return EngineInfo(
            name=self._config.display_name,
            strategy=self._config.strategy,
            model_name=self._config.model_key,
            model_size_bytes=self._model_bytes,
            supports_partials=True,
            offline=True,
            notes=self._config.notes,
        )

    # -- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        try:
            import sherpa_onnx
        except ImportError as exc:
            raise EngineUnavailable(f"sherpa-onnx not installed: {exc}") from exc

        key = self._config.model_key
        if not models.is_installed(key):
            raise EngineUnavailable(
                f"model '{key}' not installed — run scripts/download_models.py {key}"
            )
        self._model_bytes = models.dir_size_bytes(models.model_path(key))

        try:
            encoder = models.find_file(key, "encoder*.onnx", "*encoder*.onnx")
            decoder = models.find_file(key, "decoder*.onnx", "*decoder*.onnx")
            joiner = models.find_file(key, "joiner*.onnx", "*joiner*.onnx")
            tokens = models.find_file(key, "tokens.txt", "*tokens*.txt")
        except FileNotFoundError as exc:
            raise EngineUnavailable(f"{key}: {exc}") from exc

        try:
            self._recognizer = sherpa_onnx.OnlineRecognizer.from_transducer(
                tokens=str(tokens),
                encoder=str(encoder),
                decoder=str(decoder),
                joiner=str(joiner),
                num_threads=self._config.num_threads,
                sample_rate=16000,
                feature_dim=80,
                decoding_method="greedy_search",
                enable_endpoint_detection=True,
                rule1_min_trailing_silence=self._config.endpoint_silence_no_text_s,
                rule2_min_trailing_silence=self._config.endpoint_trailing_silence_s,
                rule3_min_utterance_length=300.0,
                provider="cpu",
            )
        except Exception as exc:  # noqa: BLE001
            raise EngineUnavailable(f"{key}: failed to build recognizer: {exc}") from exc

        self._reset_state()
        self._stream = self._recognizer.create_stream()
        self._audio_q = queue.Queue()
        self._events_q = queue.Queue()
        self._stop_flag = threading.Event()
        self._audio_time_s = 0.0

        self._worker = threading.Thread(
            target=self._run_worker, name=f"sherpa-{key}", daemon=True
        )
        self._worker.start()

    def feed_audio(self, samples: np.ndarray) -> None:
        self._audio_time_s += len(samples) / 16000.0
        self._audio_q.put((samples.astype(np.float32, copy=True), self._audio_time_s))

    def poll(self) -> list[SttEvent]:
        return self._record(self._drain_events())

    def stop(self) -> list[SttEvent]:
        # Sentinel tells the worker to flush the encoder and finalize whatever
        # is in flight, rather than dropping the tail of the last utterance.
        self._audio_q.put(None)
        if self._worker is not None:
            self._worker.join(timeout=60.0)
            self._worker = None
        events = self._drain_events()
        self._recognizer = None
        self._stream = None
        return self._record(events)

    # -- worker -------------------------------------------------------------

    def _drain_events(self) -> list[SttEvent]:
        out: list[SttEvent] = []
        while True:
            try:
                out.append(self._events_q.get_nowait())
            except queue.Empty:
                return out

    def _emit(self, kind: EventKind, text: str, audio_time_s: float) -> None:
        self._events_q.put(
            SttEvent(
                kind=kind,
                text=text,
                audio_time_s=audio_time_s,
                wall_time_s=time.monotonic(),
            )
        )

    def _run_worker(self) -> None:
        recognizer = self._recognizer
        stream = self._stream
        assert recognizer is not None and stream is not None

        last_partial = ""
        finished = False

        while not finished:
            item = self._audio_q.get()
            if item is None:
                stream.input_finished()
                finished = True
                audio_time = self._audio_time_s
            else:
                samples, audio_time = item
                stream.accept_waveform(16000, samples)

            while recognizer.is_ready(stream):
                recognizer.decode_stream(stream)

            text = recognizer.get_result(stream).strip()

            if recognizer.is_endpoint(stream):
                # Endpoint reached: whatever we have is the final for this
                # utterance. Reset gives the next utterance a clean decoder
                # state without reloading the model.
                if text:
                    self._emit(EventKind.FINAL, text, audio_time)
                recognizer.reset(stream)
                last_partial = ""
                continue

            if text and text != last_partial:
                self._emit(EventKind.PARTIAL, text, audio_time)
                last_partial = text

        # Stream ended without an endpoint (speaker stopped and we shut down):
        # emit the remaining hypothesis so the last sentence is never lost.
        tail = recognizer.get_result(stream).strip()
        if tail:
            self._emit(EventKind.FINAL, tail, self._audio_time_s)


# -- concrete candidates ----------------------------------------------------

ZIPFORMER_EN_KROKO = StreamingConfig(
    model_key="zipformer-en-kroko",
    display_name="Streaming Zipformer EN (Kroko 2025)",
    notes="Smallest true-streaming candidate at ~57 MB.",
)

NEMO_FASTCONFORMER_480 = StreamingConfig(
    model_key="nemo-fastconformer-480ms",
    display_name="NeMo streaming FastConformer EN 480ms (int8)",
    notes="NVIDIA FastConformer transducer, 480 ms chunk.",
)

NEMO_FASTCONFORMER_80 = StreamingConfig(
    model_key="nemo-fastconformer-80ms",
    display_name="NeMo streaming FastConformer EN 80ms (int8)",
    notes="Same family at the low-latency end of the chunk-size trade-off.",
)

PARAKEET_UNIFIED_240 = StreamingConfig(
    model_key="parakeet-unified-streaming-240ms",
    display_name="Parakeet unified EN 0.6B streaming 240ms (int8)",
    strategy="native streaming RNNT (stateful, chunked)",
    notes=(
        "NVIDIA's unified offline+streaming model. Answers the 'can Parakeet do "
        "incremental recognition' question directly — it does, natively, with no "
        "rolling-window workaround."
    ),
)

PARAKEET_UNIFIED_560 = StreamingConfig(
    model_key="parakeet-unified-streaming-560ms",
    display_name="Parakeet unified EN 0.6B streaming 560ms (int8)",
    strategy="native streaming RNNT (stateful, chunked)",
    notes="Larger chunk: more context per decode step, higher inherent latency.",
)
