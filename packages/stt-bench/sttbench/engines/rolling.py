"""Rolling-window streaming over an offline (non-streaming) ASR model.

Some strong models — whisper, Moonshine, the offline Parakeet export — have no
streaming mode at all. The standard workaround, and the one whisper.cpp's own
`stream` example uses, is to re-run the whole model over a growing buffer every
few hundred milliseconds and treat each result as the current partial.

It works, and it is the honest way to give these models a fair hearing, but the
cost profile is fundamentally worse than a streaming transducer:

  * Work is quadratic in utterance length — a 10 s question is decoded from
    scratch ~20 times, the last few times over all 10 s of audio.
  * Partials are unstable. Each re-decode is independent, so earlier words can
    change after the fact, which reads as flickering text in the UI.
  * whisper specifically pads every input to 30 s of mel spectrogram, so a 1 s
    buffer costs nearly the same as a 30 s one.

The benchmark measures all three effects rather than assuming them.
"""

from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable

import numpy as np

from ..vad import EnergyVad, VadConfig
from .base import EngineInfo, EventKind, STTEngine, SttEvent

#: A transcribe function: 16 kHz mono float32 -> text.
TranscribeFn = Callable[[np.ndarray], str]


@dataclass(frozen=True)
class RollingConfig:
    display_name: str
    model_name: str
    #: How often to re-decode while the speaker is talking. The spec asks for
    #: partial updates every 200-500 ms; 300 ms sits in the middle. If a decode
    #: takes longer than this the engine falls behind gracefully (it decodes the
    #: newest buffer available rather than queueing stale work).
    partial_interval_ms: int = 300
    #: Safety cap on utterance length. Beyond this the buffer is force-finalized
    #: so a speaker who never pauses cannot drive decode cost to infinity.
    max_utterance_s: float = 30.0
    #: Minimum audio before attempting the first partial. Below ~300 ms these
    #: models hallucinate rather than return nothing.
    min_decode_s: float = 0.4
    vad: VadConfig | None = None
    strategy: str = "rolling-window re-decode of an offline model"
    notes: str = ""


class RollingWindowSTT(STTEngine):
    def __init__(
        self,
        config: RollingConfig,
        transcribe: TranscribeFn,
        *,
        model_size_bytes: int = 0,
        loader: Callable[[], None] | None = None,
    ) -> None:
        super().__init__()
        self._config = config
        self._transcribe = transcribe
        self._loader = loader
        self._model_size_bytes = model_size_bytes
        self._vad = EnergyVad(config.vad)
        self._audio_q: queue.Queue = queue.Queue()
        self._events_q: queue.Queue = queue.Queue()
        self._worker: threading.Thread | None = None
        self._audio_time_s = 0.0
        #: Recorded so the report can show how unstable partials really are.
        self.partial_revisions = 0
        self.decode_count = 0
        self.decode_seconds_total = 0.0

    @property
    def info(self) -> EngineInfo:
        return EngineInfo(
            name=self._config.display_name,
            strategy=self._config.strategy,
            model_name=self._config.model_name,
            model_size_bytes=self._model_size_bytes,
            supports_partials=True,
            offline=True,
            notes=self._config.notes,
        )

    def start(self) -> None:
        if self._loader is not None:
            self._loader()
        self._reset_state()
        self._vad.reset()
        self._audio_q = queue.Queue()
        self._events_q = queue.Queue()
        self._audio_time_s = 0.0
        self.partial_revisions = 0
        self.decode_count = 0
        self.decode_seconds_total = 0.0
        self._worker = threading.Thread(
            target=self._run_worker, name="rolling-asr", daemon=True
        )
        self._worker.start()

    def feed_audio(self, samples: np.ndarray) -> None:
        self._audio_time_s += len(samples) / 16000.0
        self._audio_q.put((samples.astype(np.float32, copy=True), self._audio_time_s))

    def poll(self) -> list[SttEvent]:
        return self._record(self._drain())

    def stop(self) -> list[SttEvent]:
        self._audio_q.put(None)
        if self._worker is not None:
            self._worker.join(timeout=300.0)
            self._worker = None
        return self._record(self._drain())

    # -- internals ----------------------------------------------------------

    def _drain(self) -> list[SttEvent]:
        out: list[SttEvent] = []
        while True:
            try:
                out.append(self._events_q.get_nowait())
            except queue.Empty:
                return out

    def _emit(self, kind: EventKind, text: str, audio_time_s: float) -> None:
        self._events_q.put(
            SttEvent(
                kind=kind, text=text, audio_time_s=audio_time_s, wall_time_s=time.monotonic()
            )
        )

    def _decode(self, buffer: np.ndarray) -> str:
        started = time.monotonic()
        try:
            text = self._transcribe(buffer)
        except Exception as exc:  # noqa: BLE001
            # One bad decode must not kill the run; report it as empty and
            # keep going so the rest of the corpus still produces numbers.
            print(f"    [rolling] decode failed: {exc}")
            text = ""
        self.decode_count += 1
        self.decode_seconds_total += time.monotonic() - started
        return text.strip()

    def _run_worker(self) -> None:
        utterance = np.zeros(0, dtype=np.float32)
        last_partial = ""
        last_partial_at = 0.0
        audio_time = 0.0
        was_in_speech = False
        finished = False

        while not finished:
            batch = [self._audio_q.get()]
            # Drain everything else already waiting. When a decode takes longer
            # than the audio it covers — which is the normal case for whisper —
            # the queue backs up, and consuming it one chunk at a time would
            # decode a series of stale, ever-more-outdated windows. A real
            # implementation always decodes the freshest buffer it has, so the
            # benchmark does too; otherwise the measurement penalizes the
            # harness rather than the engine.
            while True:
                try:
                    batch.append(self._audio_q.get_nowait())
                except queue.Empty:
                    break

            if batch[-1] is None:
                finished = True
            samples_batch = [item for item in batch if item is not None]

            # Phase 1: run the whole batch through the VAD, accumulating the
            # current utterance. A final is emitted the moment speech ends, even
            # if that happens partway through the batch, so finalization stays
            # anchored to the real speech boundary rather than to batch edges.
            for samples, audio_time in samples_batch:
                for is_speech, frame in self._vad.process(samples):
                    # `was_in_speech and not is_speech` is the speech-to-silence
                    # transition. The hangover frames are kept either way: the
                    # tail of the last word lives in them, and dropping it is
                    # exactly how engines end up losing final words.
                    utterance = np.concatenate([utterance, frame])
                    ended = was_in_speech and not is_speech
                    was_in_speech = is_speech

                    if ended and utterance.size > 0:
                        text = self._decode(utterance)
                        if text:
                            self._emit(EventKind.FINAL, text, audio_time)
                        utterance = np.zeros(0, dtype=np.float32)
                        last_partial = ""

                    if utterance.size / 16000.0 >= self._config.max_utterance_s:
                        text = self._decode(utterance)
                        if text:
                            self._emit(EventKind.FINAL, text, audio_time)
                        utterance = np.zeros(0, dtype=np.float32)
                        last_partial = ""

            # Phase 2: at most one partial decode per pass, against the newest
            # buffer, rate-limited to the configured interval.
            now = time.monotonic()
            due = (now - last_partial_at) * 1000.0 >= self._config.partial_interval_ms
            long_enough = utterance.size / 16000.0 >= self._config.min_decode_s
            if self._vad.in_speech and due and long_enough:
                last_partial_at = now
                text = self._decode(utterance)
                if text and text != last_partial:
                    if last_partial and not text.startswith(last_partial):
                        self.partial_revisions += 1
                    self._emit(EventKind.PARTIAL, text, audio_time)
                    last_partial = text

        if utterance.size > 0:
            text = self._decode(utterance)
            if text:
                self._emit(EventKind.FINAL, text, self._audio_time_s)
