"""16 kHz mono PCM plumbing shared by the recorder and the benchmark runner.

The desktop app's WASAPI capture (`apps/desktop/src-tauri/src/audio/`) already
normalizes everything to 16 kHz mono f32 before it reaches STT, so the harness
works in exactly that format. WAV files on disk are 16-bit PCM (the universal
interchange format); conversion happens at the edges only.
"""

from __future__ import annotations

import wave
from dataclasses import dataclass
from pathlib import Path

import numpy as np

SAMPLE_RATE = 16_000
CHANNELS = 1


@dataclass(frozen=True)
class Clip:
    """A mono 16 kHz recording held as float32 in -1.0..1.0."""

    samples: np.ndarray
    sample_rate: int = SAMPLE_RATE

    @property
    def duration_s(self) -> float:
        return len(self.samples) / float(self.sample_rate)

    def to_pcm16(self) -> bytes:
        clipped = np.clip(self.samples, -1.0, 1.0)
        return (clipped * 32767.0).astype("<i2").tobytes()


def read_wav(path: str | Path) -> Clip:
    """Reads a 16-bit PCM WAV. Raises if it is not already 16 kHz mono, because
    silently resampling here would mean different engines are scored on subtly
    different audio."""
    with wave.open(str(path), "rb") as wf:
        if wf.getsampwidth() != 2:
            raise ValueError(f"{path}: expected 16-bit PCM, got {wf.getsampwidth() * 8}-bit")
        if wf.getnchannels() != CHANNELS:
            raise ValueError(f"{path}: expected mono, got {wf.getnchannels()} channels")
        if wf.getframerate() != SAMPLE_RATE:
            raise ValueError(f"{path}: expected {SAMPLE_RATE} Hz, got {wf.getframerate()} Hz")
        raw = wf.readframes(wf.getnframes())
    samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    return Clip(samples)


def write_wav(path: str | Path, clip: Clip) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(CHANNELS)
        wf.setsampwidth(2)
        wf.setframerate(clip.sample_rate)
        wf.writeframes(clip.to_pcm16())


def chunk(clip: Clip, chunk_ms: int) -> list[np.ndarray]:
    """Splits a clip into fixed-size chunks, mimicking how audio actually arrives
    from WASAPI. The final short chunk is kept rather than padded, so an engine
    cannot get a free extra window of silence to finalize in."""
    step = int(SAMPLE_RATE * chunk_ms / 1000)
    if step <= 0:
        raise ValueError("chunk_ms too small")
    return [clip.samples[i : i + step] for i in range(0, len(clip.samples), step)]


def pad_silence(clip: Clip, ms: int) -> Clip:
    """Appends trailing silence. Real speech is followed by room tone, and every
    endpointing engine needs some trailing silence to declare the utterance
    over; without it we would be measuring an artifact of the file ending."""
    pad = np.zeros(int(SAMPLE_RATE * ms / 1000), dtype=np.float32)
    return Clip(np.concatenate([clip.samples, pad]), clip.sample_rate)


def rms(samples: np.ndarray) -> float:
    if samples.size == 0:
        return 0.0
    return float(np.sqrt(np.mean(np.square(samples.astype(np.float64)))))


def peak_dbfs(samples: np.ndarray) -> float:
    if samples.size == 0:
        return -999.0
    peak = float(np.max(np.abs(samples)))
    if peak <= 0.0:
        return -999.0
    return 20.0 * float(np.log10(peak))
