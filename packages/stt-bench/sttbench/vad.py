"""Lightweight energy VAD.

Scope, deliberately narrow: this answers exactly one question — *is someone
speaking right now?* It never inspects words and never decides whether an
utterance is a question. That determination does not exist anywhere in this
system by design.

Two jobs:
  1. Skip ASR work during silence (the rolling-window engines would otherwise
     burn CPU re-decoding room tone).
  2. Mark the speech-to-silence transition that ends an utterance.

Energy-based with an adaptive noise floor and a hangover timer. No model, no
allocation per frame, roughly a microsecond per 20 ms frame — cheap enough to
run on the audio thread. A neural VAD (Silero) would be more robust to
background noise but costs a model load and ~1 ms per frame, which is not
warranted for the clean single-speaker audio this product sees.
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
    #: 3 frames = 60 ms, enough to reject a keyboard click.
    attack_frames: int = 3
    #: Silence to tolerate before declaring speech ended. This is the dominant
    #: term in finalization latency, so it is tuned against the 300-800 ms
    #: budget rather than left at a conservative default.
    hangover_ms: int = 500
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
