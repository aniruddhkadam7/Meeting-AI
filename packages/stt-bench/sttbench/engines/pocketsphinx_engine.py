"""PocketSphinx baseline — the engine currently shipping in the app.

This deliberately mirrors `packages/stt/pocketsphinx_sidecar/sidecar.py` as
closely as possible: same `Endpointer`, same 450 ms end-silence window, same
merged tech-vocabulary dictionary. If the baseline here were configured any
differently, the comparison would be against a straw man rather than against
what the product actually does today.

Decoding runs inline in `feed_audio` because PocketSphinx is far faster than
real time and its API is not thread-safe; the runner measures wall-clock time
around the call either way, so this does not flatter it.
"""

from __future__ import annotations

import os
import tempfile
import time
from pathlib import Path

import numpy as np

from .base import EngineInfo, EngineUnavailable, EventKind, STTEngine, SttEvent

#: Same default as the production sidecar's STT_END_SILENCE_MS.
DEFAULT_END_SILENCE_MS = 450

TECH_VOCAB_PATH = (
    Path(__file__).resolve().parents[4] / "models" / "pocketsphinx" / "tech_vocab.dict"
)


def _merged_dictionary(base_dict_path: str) -> str:
    """Same merge the production sidecar performs, so the baseline gets the
    benefit of the tech-vocabulary work already done."""
    if not TECH_VOCAB_PATH.exists():
        return base_dict_path
    try:
        with open(base_dict_path, encoding="latin-1") as f:
            base_lines = f.readlines()
        with open(TECH_VOCAB_PATH, encoding="utf-8") as f:
            supp_lines = [line for line in f if line.strip()]
        supp_words = {line.split()[0].lower() for line in supp_lines}
        filtered = [ln for ln in base_lines if ln.split()[0].lower() not in supp_words]
        fd, merged = tempfile.mkstemp(suffix=".dict", prefix="sttbench_ps_")
        with os.fdopen(fd, "w", encoding="latin-1") as f:
            f.writelines(filtered)
            f.writelines(supp_lines)
        return merged
    except OSError:
        return base_dict_path


class PocketSphinxSTT(STTEngine):
    def __init__(self, end_silence_ms: int = DEFAULT_END_SILENCE_MS) -> None:
        super().__init__()
        self._end_silence_ms = end_silence_ms
        self._decoder = None
        self._endpointer = None
        self._pending = bytearray()
        self._in_utt = False
        self._audio_time_s = 0.0
        self._events: list[SttEvent] = []
        self._model_bytes = 0

    @property
    def info(self) -> EngineInfo:
        return EngineInfo(
            name=f"PocketSphinx (baseline, {self._end_silence_ms}ms end-silence)",
            strategy="HMM + trigram LM, energy endpointer, incremental decode",
            model_name="pocketsphinx en-us (bundled)",
            model_size_bytes=self._model_bytes,
            supports_partials=True,
            offline=True,
            notes="Current production engine. Included as the bar to beat.",
        )

    def start(self) -> None:
        try:
            from pocketsphinx import Config, Decoder, Endpointer
        except ImportError as exc:
            raise EngineUnavailable(f"pocketsphinx not installed: {exc}") from exc

        self._reset_state()
        config = Config()
        config["samprate"] = 16000
        base_dict = config.get_string("dict")
        if base_dict:
            config["dict"] = _merged_dictionary(base_dict)

        hmm = config.get_string("hmm")
        if hmm and Path(hmm).exists():
            self._model_bytes = sum(
                f.stat().st_size for f in Path(hmm).rglob("*") if f.is_file()
            )

        self._decoder = Decoder(config)
        self._endpointer = Endpointer(
            sample_rate=16000, window=self._end_silence_ms / 1000.0
        )
        self._pending = bytearray()
        self._in_utt = False
        self._audio_time_s = 0.0
        self._events = []

    def feed_audio(self, samples: np.ndarray) -> None:
        if self._endpointer is None or self._decoder is None:
            raise RuntimeError("start() not called")

        self._audio_time_s += len(samples) / 16000.0
        pcm = (np.clip(samples, -1.0, 1.0) * 32767.0).astype("<i2").tobytes()
        self._pending.extend(pcm)

        frame_bytes = self._endpointer.frame_bytes
        while len(self._pending) >= frame_bytes:
            frame = bytes(self._pending[:frame_bytes])
            del self._pending[:frame_bytes]

            was_in_speech = self._endpointer.in_speech
            speech = self._endpointer.process(frame)
            if speech is None:
                continue

            if not self._in_utt:
                self._decoder.start_utt()
                self._in_utt = True
            self._decoder.process_raw(speech, no_search=False, full_utt=False)

            if was_in_speech and not self._endpointer.in_speech:
                self._finalize()
            else:
                hyp = self._decoder.hyp()
                if hyp and hyp.hypstr.strip():
                    self._emit(EventKind.PARTIAL, hyp.hypstr.strip())

    def _finalize(self) -> None:
        if not self._in_utt or self._decoder is None:
            return
        self._decoder.end_utt()
        hyp = self._decoder.hyp()
        text = hyp.hypstr.strip() if hyp else ""
        self._in_utt = False
        if text:
            self._emit(EventKind.FINAL, text)

    def _emit(self, kind: EventKind, text: str) -> None:
        self._events.append(
            SttEvent(
                kind=kind,
                text=text,
                audio_time_s=self._audio_time_s,
                wall_time_s=time.monotonic(),
            )
        )

    def poll(self) -> list[SttEvent]:
        out, self._events = self._events, []
        return self._record(out)

    def stop(self) -> list[SttEvent]:
        self._finalize()
        out, self._events = self._events, []
        self._decoder = None
        self._endpointer = None
        return self._record(out)
