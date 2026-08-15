"""Offline sherpa-onnx models driven as rolling-window streaming engines.

Two candidates land here because they have no streaming export:

  * Moonshine base EN — built for very short clips, so it should suffer less
    than whisper from repeated re-decoding.
  * Parakeet unified EN 0.6B, offline export — included as the accuracy
    ceiling. Comparing it against the same model's streaming export is the
    cleanest available measurement of what streaming actually costs in
    accuracy, since the weights and training data are identical.
"""

from __future__ import annotations

import numpy as np

from .. import models
from .base import EngineUnavailable
from .rolling import RollingConfig, RollingWindowSTT


def _build(
    model_key: str,
    display_name: str,
    factory_name: str,
    notes: str,
    *,
    partial_interval_ms: int = 300,
    num_threads: int = 4,
) -> RollingWindowSTT:
    state: dict = {"recognizer": None, "engine": None}

    def loader() -> None:
        try:
            import sherpa_onnx
        except ImportError as exc:
            raise EngineUnavailable(f"sherpa-onnx not installed: {exc}") from exc

        if not models.is_installed(model_key):
            raise EngineUnavailable(
                f"model '{model_key}' not installed — run scripts/download_models.py {model_key}"
            )

        try:
            if factory_name == "moonshine":
                # The 2026 Moonshine release ships the v2 layout — a merged
                # decoder in ONNX Runtime `.ort` format — rather than the four
                # separate `.onnx` graphs the original export used.
                recognizer = sherpa_onnx.OfflineRecognizer.from_moonshine_v2(
                    encoder=str(models.find_file(model_key, "encoder_model.ort", "encoder*.ort", "encode*.onnx")),
                    decoder=str(
                        models.find_file(
                            model_key, "decoder_model_merged.ort", "decoder*.ort", "decode*.onnx"
                        )
                    ),
                    tokens=str(models.find_file(model_key, "tokens.txt")),
                    num_threads=num_threads,
                    provider="cpu",
                )
            elif factory_name == "transducer":
                recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
                    encoder=str(models.find_file(model_key, "encoder*.onnx")),
                    decoder=str(models.find_file(model_key, "decoder*.onnx")),
                    joiner=str(models.find_file(model_key, "joiner*.onnx")),
                    tokens=str(models.find_file(model_key, "tokens.txt")),
                    num_threads=num_threads,
                    provider="cpu",
                    model_type="nemo_transducer",
                )
            else:
                raise EngineUnavailable(f"unknown factory '{factory_name}'")
        except EngineUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            raise EngineUnavailable(f"{model_key}: failed to build recognizer: {exc}") from exc

        state["recognizer"] = recognizer
        if state["engine"] is not None:
            state["engine"]._model_size_bytes = models.dir_size_bytes(
                models.model_path(model_key)
            )

    def transcribe(buffer: np.ndarray) -> str:
        recognizer = state["recognizer"]
        if recognizer is None:
            return ""
        stream = recognizer.create_stream()
        stream.accept_waveform(16000, buffer.astype(np.float32))
        recognizer.decode_stream(stream)
        return stream.result.text.strip()

    engine = RollingWindowSTT(
        RollingConfig(
            display_name=display_name,
            model_name=model_key,
            partial_interval_ms=partial_interval_ms,
            notes=notes,
        ),
        transcribe,
        loader=loader,
    )
    state["engine"] = engine
    return engine


def moonshine_base_en(**kwargs) -> RollingWindowSTT:
    return _build(
        "moonshine-base-en",
        "Moonshine base EN (rolling window)",
        "moonshine",
        "Offline model designed for short-clip latency; no streaming export exists.",
        **kwargs,
    )


def parakeet_unified_offline(**kwargs) -> RollingWindowSTT:
    return _build(
        "parakeet-unified-offline",
        "Parakeet unified EN 0.6B offline (rolling window)",
        "transducer",
        (
            "Accuracy ceiling. Same weights as the streaming export, so the gap "
            "between the two is exactly the price of streaming."
        ),
        **kwargs,
    )
