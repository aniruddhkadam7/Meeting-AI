"""Model registry and one-time downloader.

Requirement: models are downloaded **once** into an application-managed
directory and the system works fully offline afterwards. Nothing here runs at
engine start-up — `ensure_model()` is a no-op when the directory already
exists, so a benchmark run never touches the network.

Model directory layout:

    models/stt-bench/<model-key>/...

`models/` sits at the repo root next to the existing `models/pocketsphinx/`.
For production this would move to the app's AppData directory; the resolver
below already honours `STT_MODEL_DIR` so the same code can be pointed there
without modification.
"""

from __future__ import annotations

import os
import shutil
import tarfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

SHERPA_RELEASE = "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models"


@dataclass(frozen=True)
class ModelSpec:
    key: str
    url: str
    #: Directory name inside the tarball, which is not always the same as `key`.
    archive_root: str
    approx_mb: int
    description: str


#: Every candidate model the benchmark can use. Deliberately spans the whole
#: size range (57 MB .. 500 MB) and both decoding strategies, so the report can
#: say something about the accuracy/footprint trade-off rather than just naming
#: a winner.
REGISTRY: dict[str, ModelSpec] = {
    # --- true streaming transducers (native partial results) ---------------
    "zipformer-en-kroko": ModelSpec(
        key="zipformer-en-kroko",
        url=f"{SHERPA_RELEASE}/sherpa-onnx-streaming-zipformer-en-kroko-2025-08-06.tar.bz2",
        archive_root="sherpa-onnx-streaming-zipformer-en-kroko-2025-08-06",
        approx_mb=57,
        description="Streaming Zipformer transducer, English, 2025 Kroko release. Smallest true-streaming candidate.",
    ),
    "nemo-fastconformer-480ms": ModelSpec(
        key="nemo-fastconformer-480ms",
        url=f"{SHERPA_RELEASE}/sherpa-onnx-nemo-streaming-fast-conformer-transducer-en-480ms-int8.tar.bz2",
        archive_root="sherpa-onnx-nemo-streaming-fast-conformer-transducer-en-480ms-int8",
        approx_mb=106,
        description="NVIDIA NeMo streaming FastConformer transducer, English, 480 ms chunk, int8.",
    ),
    "nemo-fastconformer-80ms": ModelSpec(
        key="nemo-fastconformer-80ms",
        url=f"{SHERPA_RELEASE}/sherpa-onnx-nemo-streaming-fast-conformer-transducer-en-80ms-int8.tar.bz2",
        archive_root="sherpa-onnx-nemo-streaming-fast-conformer-transducer-en-80ms-int8",
        approx_mb=103,
        description="Same family at 80 ms chunk — the low-latency end of the trade-off.",
    ),
    "parakeet-unified-streaming-240ms": ModelSpec(
        key="parakeet-unified-streaming-240ms",
        url=f"{SHERPA_RELEASE}/sherpa-onnx-nemo-parakeet-unified-en-0.6b-int8-streaming-240ms.tar.bz2",
        archive_root="sherpa-onnx-nemo-parakeet-unified-en-0.6b-int8-streaming-240ms",
        approx_mb=501,
        description=(
            "NVIDIA Parakeet unified EN 0.6B, int8, native streaming export at 240 ms. "
            "This is genuine stateful streaming RNNT — not a rolling window over an offline model."
        ),
    ),
    "parakeet-unified-streaming-560ms": ModelSpec(
        key="parakeet-unified-streaming-560ms",
        url=f"{SHERPA_RELEASE}/sherpa-onnx-nemo-parakeet-unified-en-0.6b-int8-streaming-560ms.tar.bz2",
        archive_root="sherpa-onnx-nemo-parakeet-unified-en-0.6b-int8-streaming-560ms",
        approx_mb=501,
        description="Same Parakeet unified model at 560 ms chunk — trades latency for accuracy.",
    ),
    # --- rolling-window / offline models re-decoded over a sliding buffer ---
    "moonshine-base-en": ModelSpec(
        key="moonshine-base-en",
        url=f"{SHERPA_RELEASE}/sherpa-onnx-moonshine-base-en-quantized-2026-02-27.tar.bz2",
        archive_root="sherpa-onnx-moonshine-base-en-quantized-2026-02-27",
        approx_mb=111,
        description="Moonshine base English, quantized. Offline model built for very short-clip latency.",
    ),
    "parakeet-unified-offline": ModelSpec(
        key="parakeet-unified-offline",
        url=f"{SHERPA_RELEASE}/sherpa-onnx-nemo-parakeet-unified-en-0.6b-int8-non-streaming.tar.bz2",
        archive_root="sherpa-onnx-nemo-parakeet-unified-en-0.6b-int8-non-streaming",
        approx_mb=501,
        description=(
            "The same Parakeet unified model in its offline export. Included as the accuracy "
            "ceiling: it shows what the streaming export gives up."
        ),
    ),
}


def model_root() -> Path:
    """Resolves the application-managed model directory."""
    override = os.environ.get("STT_MODEL_DIR", "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[3] / "models" / "stt-bench"


def model_path(key: str) -> Path:
    return model_root() / key


def is_installed(key: str) -> bool:
    path = model_path(key)
    return path.is_dir() and any(path.iterdir())


def dir_size_bytes(path: Path) -> int:
    if not path.exists():
        return 0
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def ensure_model(key: str, *, quiet: bool = False) -> Path:
    """Downloads and extracts a model if it is not already installed.

    Returns the model directory. Raises `KeyError` for an unknown key and
    `RuntimeError` if the download or extraction fails.
    """
    spec = REGISTRY[key]
    target = model_path(key)
    if is_installed(key):
        return target

    target.parent.mkdir(parents=True, exist_ok=True)
    archive = target.parent / f"{key}.tar.bz2"

    # Report at 10% granularity only. A per-block reporter writes tens of
    # thousands of lines when stdout is a file rather than a terminal.
    last_step = [-1]

    def report(done: int, block: int, total: int) -> None:
        if quiet or total <= 0:
            return
        step = int(min(100.0, done * block * 100.0 / total)) // 10
        if step > last_step[0]:
            last_step[0] = step
            print(f"    {key}: {step * 10}% of {total / 1e6:.0f} MB", flush=True)

    try:
        if not quiet:
            print(f"  downloading {key} (~{spec.approx_mb} MB)")
        urllib.request.urlretrieve(spec.url, archive, reporthook=report)
        if not quiet:
            print()

        extract_dir = target.parent / f"_extract_{key}"
        if extract_dir.exists():
            shutil.rmtree(extract_dir)
        with tarfile.open(archive, "r:bz2") as tf:
            # `filter="data"` rejects absolute paths and symlinks escaping the
            # destination — these archives are third-party downloads.
            tf.extractall(extract_dir, filter="data")

        extracted = extract_dir / spec.archive_root
        if not extracted.is_dir():
            candidates = [p for p in extract_dir.iterdir() if p.is_dir()]
            if len(candidates) != 1:
                raise RuntimeError(
                    f"unexpected archive layout for {key}: {[p.name for p in extract_dir.iterdir()]}"
                )
            extracted = candidates[0]

        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(extracted), str(target))
        shutil.rmtree(extract_dir, ignore_errors=True)
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(f"failed to install model {key}: {exc}") from exc
    finally:
        archive.unlink(missing_ok=True)

    return target


def find_file(key: str, *patterns: str) -> Path:
    """Locates a file inside an installed model directory by glob pattern,
    trying each pattern in order. Model archives are not consistent about
    naming (`encoder.onnx` vs `encoder-epoch-99-avg-1.onnx`), so engines
    describe what they want rather than hardcoding a filename."""
    root = model_path(key)
    for pattern in patterns:
        matches = sorted(root.glob(pattern))
        if matches:
            return matches[0]
    raise FileNotFoundError(
        f"none of {patterns} found in {root} "
        f"(contents: {[p.name for p in root.iterdir()] if root.exists() else 'missing'})"
    )
