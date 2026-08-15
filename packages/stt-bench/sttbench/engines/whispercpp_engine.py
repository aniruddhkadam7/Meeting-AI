"""whisper.cpp via pywhispercpp, driven as a rolling-window streaming engine.

whisper has no streaming mode. Its encoder consumes a fixed 30-second mel
window, so "streaming whisper" always means re-running the model over a growing
buffer — the approach whisper.cpp's own `stream` example takes and the one
implemented here.

Two knobs matter for making that bearable and both are set deliberately:

  * `audio_ctx` truncates the encoder's context to roughly the audio we
    actually have instead of the full 30 s. Without it a 1-second buffer costs
    the same as a 30-second one, which is the single biggest reason naive
    streaming whisper feels slow.
  * `single_segment` stops whisper from splitting a short buffer into multiple
    segments with their own timestamps, which we would only have to re-join.

Greedy sampling (`beam_search=False`) is used for partials because beam search
multiplies decode cost for an intermediate result that will be thrown away.
"""

from __future__ import annotations

import re
from pathlib import Path

import numpy as np

#: whisper annotates non-speech with bracketed tags — [BLANK_AUDIO], (wind
#: blowing), ♪♪♪. They are annotations, not transcription, so they are stripped
#: rather than scored as inserted words; leaving them in would penalize whisper
#: for a formatting convention rather than for what it actually heard.
_NON_SPEECH_TAG = re.compile(r"[\[\(][^\]\)]*[\]\)]|[♪*]+")

from .base import EngineUnavailable
from .rolling import RollingConfig, RollingWindowSTT

#: Keep whisper's GGML weights in the same application-managed directory as
#: everything else rather than pywhispercpp's default under LOCALAPPDATA.
def _models_dir() -> Path:
    from .. import models

    path = models.model_root() / "whispercpp"
    path.mkdir(parents=True, exist_ok=True)
    return path


#: Whisper's encoder works in 20 ms frames; 1500 is the full 30 s context.
#: Scaling it to the buffer length is what makes short-buffer decodes cheap.
_FULL_AUDIO_CTX = 1500


def _audio_ctx_for(seconds: float) -> int:
    frames = int(seconds * 50) + 64  # 50 frames/s, plus headroom
    return max(256, min(_FULL_AUDIO_CTX, frames))


def build(model_name: str = "base.en", *, partial_interval_ms: int = 300) -> RollingWindowSTT:
    """Creates a whisper.cpp rolling-window engine.

    `model_name` is any pywhispercpp model id: `tiny.en`, `base.en`,
    `small.en`, ... The GGML weights are downloaded once on first use into the
    shared model directory and reused thereafter.
    """
    state: dict = {"model": None, "engine": None}

    def loader() -> None:
        try:
            from pywhispercpp.model import Model
        except ImportError as exc:
            raise EngineUnavailable(f"pywhispercpp not installed: {exc}") from exc
        try:
            state["model"] = Model(
                model=model_name,
                models_dir=str(_models_dir()),
                # 0 = greedy. Beam search multiplies decode cost for partials
                # that get thrown away on the next window, so it is not worth
                # it here. Set at construction because pywhispercpp's per-call
                # `beam_search` parameter takes a dict, not a flag.
                params_sampling_strategy=0,
                redirect_whispercpp_logs_to=False,
                print_progress=False,
                print_realtime=False,
                language="en",
                translate=False,
                single_segment=True,
                no_context=True,
                suppress_blank=True,
            )
        except Exception as exc:  # noqa: BLE001
            raise EngineUnavailable(
                f"whisper.cpp model '{model_name}' unavailable: {exc}"
            ) from exc

        # Size is only knowable after the loader has downloaded the weights,
        # so it is written back onto the engine here rather than guessed at
        # construction time.
        weights = sorted(_models_dir().glob(f"*{model_name}*.bin"))
        if weights and state["engine"] is not None:
            state["engine"]._model_size_bytes = weights[0].stat().st_size

    def transcribe(buffer: np.ndarray) -> str:
        model = state["model"]
        if model is None:
            return ""
        seconds = len(buffer) / 16000.0
        # whisper.cpp rejects buffers shorter than ~1 s; pad rather than skip so
        # the first partial still arrives early instead of waiting a full second.
        if seconds < 1.0:
            buffer = np.concatenate(
                [buffer, np.zeros(int(16000 * (1.0 - seconds)), dtype=np.float32)]
            )
        segments = model.transcribe(
            buffer.astype(np.float32),
            audio_ctx=_audio_ctx_for(max(seconds, 1.0)),
        )
        text = " ".join(s.text.strip() for s in segments)
        return re.sub(r"\s+", " ", _NON_SPEECH_TAG.sub(" ", text)).strip()

    engine = RollingWindowSTT(
        RollingConfig(
            display_name=f"whisper.cpp {model_name} (rolling window)",
            model_name=f"ggml-{model_name}",
            partial_interval_ms=partial_interval_ms,
            strategy="rolling-window re-decode (whisper has no streaming mode)",
            notes=(
                "audio_ctx scaled to buffer length; greedy sampling for partials. "
                "Cost grows with utterance length because every partial re-decodes "
                "the whole utterance from scratch."
            ),
        ),
        transcribe,
        loader=loader,
    )
    state["engine"] = engine
    return engine
