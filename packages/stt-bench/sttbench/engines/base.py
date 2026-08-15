"""The `STTEngine` contract every candidate must satisfy.

This is the seam the whole spike exists to establish. The desktop app currently
talks to PocketSphinx through a bespoke sidecar protocol; the point of this
interface is that swapping the engine underneath must not require touching
WASAPI capture, the transcript manager, the Tauri commands, the overlay, RAG or
the LLM path.

Lifecycle
---------
    engine.start()
    while audio:
        engine.feed_audio(samples)      # 16 kHz mono float32, any length
        for ev in engine.poll():        # non-blocking; partials and finals
            ...
    engine.stop()                       # flushes; returns remaining events

`feed_audio` must never block on inference. Engines that need real work done
(neural decoders) do it on their own worker thread and surface results through
`poll()`, which is what keeps the UI thread free in the real application.

Timing
------
Every event carries `audio_time_s` (position in the audio stream when the
event was produced) and `wall_time_s` (monotonic clock). Latency metrics are
derived from the gap between them, so an engine cannot look fast by being fed
audio faster than real time — the runner paces input at 1x.
"""

from __future__ import annotations

import abc
import time
from dataclasses import dataclass, field
from enum import Enum

import numpy as np


class EventKind(str, Enum):
    PARTIAL = "partial"
    FINAL = "final"


@dataclass
class SttEvent:
    kind: EventKind
    text: str
    #: Stream position (seconds of audio fed) at which this event was emitted.
    audio_time_s: float
    #: Monotonic wall-clock timestamp at which this event was emitted.
    wall_time_s: float = field(default_factory=time.monotonic)

    @property
    def is_final(self) -> bool:
        return self.kind is EventKind.FINAL


@dataclass(frozen=True)
class EngineInfo:
    """Static facts used by the report. `model_size_bytes` is the on-disk
    footprint the user would have to download and ship."""

    name: str
    #: Human-readable description of the decoding strategy, e.g.
    #: "true streaming transducer" vs "rolling-window re-decode".
    strategy: str
    model_name: str
    model_size_bytes: int
    #: True when the engine emits meaningful text before the utterance ends.
    supports_partials: bool
    #: True when no network access is required after model installation.
    offline: bool
    notes: str = ""


class STTEngine(abc.ABC):
    """Base class for every benchmarked engine.

    Subclasses own their model and worker threads. They are constructed cheaply;
    all expensive setup (model load) happens in `start()` so that load time is
    measured separately from steady-state decoding.
    """

    def __init__(self) -> None:
        # Instance-level, not class-level: a class attribute here would be one
        # shared list across every engine, silently merging one engine's
        # transcript into the next one's results.
        self._latest_partial: str = ""
        self._finals: list[str] = []

    @property
    @abc.abstractmethod
    def info(self) -> EngineInfo: ...

    @abc.abstractmethod
    def start(self) -> None:
        """Loads the model and starts worker threads. Called once per run."""

    @abc.abstractmethod
    def feed_audio(self, samples: np.ndarray) -> None:
        """Accepts 16 kHz mono float32 samples. Must return promptly — never
        block on inference."""

    @abc.abstractmethod
    def poll(self) -> list[SttEvent]:
        """Returns any events produced since the last call. Non-blocking."""

    @abc.abstractmethod
    def stop(self) -> list[SttEvent]:
        """Flushes in-flight audio, finalizes the current utterance, tears down
        workers, and returns any remaining events."""

    # -- convenience used by the runner -------------------------------------

    def get_partial(self) -> str:
        """Most recent partial hypothesis. Provided for parity with the
        interface named in the spec; the runner uses `poll()` because it also
        needs the timing of each update."""
        return self._latest_partial

    def get_final(self) -> str:
        """Concatenated finalized text so far."""
        return " ".join(self._finals).strip()

    def _record(self, events: list[SttEvent]) -> list[SttEvent]:
        """Bookkeeping helper so `get_partial()`/`get_final()` stay correct
        regardless of which subclass produced the events."""
        for event in events:
            if event.is_final:
                if event.text.strip():
                    self._finals.append(event.text.strip())
                self._latest_partial = ""
            else:
                self._latest_partial = event.text
        return events

    def _reset_state(self) -> None:
        self._latest_partial = ""
        self._finals = []


class EngineUnavailable(RuntimeError):
    """Raised by `start()` when an engine's model or runtime is not installed.

    The runner treats this as "skip and report why" rather than a crash, so one
    missing dependency never invalidates the whole benchmark run.
    """
