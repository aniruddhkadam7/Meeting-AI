"""Lightweight energy VAD — gates expensive FastConformer inference, never
decides when an utterance ends.

Ported from `packages/stt-bench/sttbench/vad.py` (the existing, already-
designed-for-this-purpose energy VAD used to bake off STT engines) rather
than adding a new dependency — see that module's docstring for the full
design rationale. This copy is trimmed to exactly what the production
sidecar needs and kept dependency-free (numpy only, already a hard
dependency of `sherpa_onnx`).

Scope, deliberately narrow — same as the original: this answers exactly one
question, *is someone speaking right now?* It never inspects words, never
touches endpointing, and never decides whether an utterance is finished.
`sidecar.py`'s existing `rule1_min_trailing_silence`/
`rule2_min_trailing_silence`/`rule3_min_utterance_length`
(sherpa-onnx's own endpoint detection) is untouched by this module and
remains the sole authority on when to finalize.

Integration contract (see `sidecar.py`'s worker loop, and `should_decode`
below):
    - `stream.accept_waveform(...)` is ALWAYS called, VAD state notwithstanding
      — audio is never dropped from the decoder's own buffer.
    - `decode_stream()` is skipped ONLY before any speech has been observed
      in the current utterance (i.e. while waiting for an utterance to
      begin). Once speech starts, every subsequent chunk decodes normally
      all the way through the endpoint firing — never gated again until the
      next utterance.

Why not gate on silence AFTER speech too (the naive, more-aggressive
design): sherpa-onnx's own endpoint detection measures trailing silence
against DECODED audio, not wall-clock time (its docstring: "if we have
decoded something that is nonsilence and the duration of trailing silence
[since the last decode] exceeds rule2_min_trailing_silence..."). An earlier
version of this gate skipped decode_stream() once the VAD's own hangover
window elapsed, which starves the endpointer of the evaluation it needs to
ever fire — measured regression: finalize latency 353ms -> 2865ms with WER
unchanged (see docs/stt-performance-phase2.md). Gating only pre-speech
silence avoids this entirely: the endpointer is never involved until real
speech has been decoded at least once, at which point this module gets out
of its way completely for the rest of that utterance.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

FRAME_MS = 20
SAMPLE_RATE = 16_000
FRAME_SAMPLES = SAMPLE_RATE * FRAME_MS // 1000


@dataclass
class VadConfig:
    #: Speech must exceed the noise floor by this many dB to count.
    threshold_db: float = 9.0
    #: Absolute floor: below this, never call it speech regardless of the
    #: adaptive floor (stops the VAD latching onto a dead-silent stream).
    absolute_floor_db: float = -55.0
    #: Consecutive speech frames required before declaring speech started.
    #: 3 frames = 60 ms — bounds how long decode can be deferred after real
    #: speech begins (accept_waveform still buffers it; see module doc).
    attack_frames: int = 3
    #: Silence to tolerate before flipping back to "not speech" (i.e. before
    #: decode_stream() calls may be skipped again). Deliberately LONGER than
    #: sidecar.py's own end-of-utterance silence budget (default 600ms) so
    #: the VAD gate is never the thing that decides an utterance is over —
    #: sherpa-onnx's endpointer, which keeps seeing every decoded frame
    #: throughout this whole window, gets there first in every real case.
    hangover_ms: int = 700
    #: How fast the noise floor tracks the signal when not in speech.
    floor_adapt: float = 0.05


class EnergyVad:
    def __init__(self, config: VadConfig | None = None) -> None:
        self.config = config or VadConfig()
        self._noise_floor_db = -60.0
        self._speech_run = 0
        self._silence_ms = 0
        self._in_speech = False
        self._buffer = np.zeros(0, dtype=np.float32)

    @property
    def in_speech(self) -> bool:
        return self._in_speech

    @property
    def noise_floor_db(self) -> float:
        return self._noise_floor_db

    def reset(self) -> None:
        self._speech_run = 0
        self._silence_ms = 0
        self._in_speech = False
        self._buffer = np.zeros(0, dtype=np.float32)

    def process(self, samples: np.ndarray) -> list[tuple[bool, np.ndarray]]:
        """Feeds samples and returns `(is_speech, frame)` for each complete
        20 ms frame consumed. Leftover samples are retained for the next call,
        so callers may pass arbitrary chunk sizes."""
        self._buffer = (
            samples.astype(np.float32)
            if self._buffer.size == 0
            else np.concatenate([self._buffer, samples.astype(np.float32)])
        )

        out: list[tuple[bool, np.ndarray]] = []
        while self._buffer.size >= FRAME_SAMPLES:
            frame = self._buffer[:FRAME_SAMPLES]
            self._buffer = self._buffer[FRAME_SAMPLES:]
            out.append((self._process_frame(frame), frame))
        return out

    def _process_frame(self, frame: np.ndarray) -> bool:
        rms = float(np.sqrt(np.mean(np.square(frame.astype(np.float64)))))
        db = 20.0 * np.log10(rms) if rms > 1e-9 else -120.0

        loud_enough = (
            db > self._noise_floor_db + self.config.threshold_db
            and db > self.config.absolute_floor_db
        )

        if loud_enough:
            self._speech_run += 1
            self._silence_ms = 0
            if self._speech_run >= self.config.attack_frames:
                self._in_speech = True
        else:
            self._speech_run = 0
            # Track the noise floor only while not speaking, so a long vowel
            # cannot drag the floor up and cut the speaker off mid-word.
            if not self._in_speech:
                a = self.config.floor_adapt
                self._noise_floor_db = (1 - a) * self._noise_floor_db + a * db
            else:
                self._silence_ms += FRAME_MS
                if self._silence_ms >= self.config.hangover_ms:
                    self._in_speech = False
                    self._silence_ms = 0

        return self._in_speech


class UtteranceGate:
    """Stateful wrapper around `EnergyVad` implementing the ONE decode-
    skipping rule this module is safe to apply (see module doc): skip
    `decode_stream()` only before any speech has been observed in the
    current utterance; once speech starts, always decode until the caller
    resets the gate (on endpoint fire or explicit flush).

    Kept as a small, independently testable unit — see `test_vad.py`'s
    `UtteranceGateTests` — rather than inlined in `sidecar.py`'s worker
    closure, so `sidecar.py` and `packages/stt-bench`'s benchmark engine
    mirror can both exercise identical, tested logic instead of two
    hand-copied implementations drifting apart.
    """

    def __init__(self, vad: EnergyVad) -> None:
        self._vad = vad
        self._utterance_has_speech = False

    def observe(self, samples: "np.ndarray") -> bool:
        """Feeds `samples` to the underlying VAD and returns whether the
        caller should run decode_stream() for this chunk. Must be called
        exactly once per chunk, after `accept_waveform` (which the caller is
        responsible for calling unconditionally — this method never touches
        the recognizer/stream)."""
        frame_results = self._vad.process(samples)
        if frame_results and any(is_speech for is_speech, _ in frame_results):
            self._utterance_has_speech = True
        # Empty frame_results (chunk smaller than one 20ms frame, buffered
        # internally by EnergyVad) must decode — there's nothing yet to base
        # a skip decision on, and erring toward decoding is always safe.
        return self._utterance_has_speech or self._vad.in_speech or not frame_results

    def reset(self) -> None:
        """Call on endpoint fire or explicit flush — starts the next
        utterance from a clean "no speech observed yet" state."""
        self._vad.reset()
        self._utterance_has_speech = False
