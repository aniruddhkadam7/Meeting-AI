"""One-time installer for the production STT model.

    py -3 packages/stt/scripts/install_model.py

Downloads NVIDIA NeMo streaming FastConformer (English, 80 ms chunk, int8) into
`models/stt/nemo-fastconformer-80ms-int8/`. Roughly 103 MB compressed, ~132 MB
on disk.

Run once at setup. The application never downloads at start-up and never
contacts the network during recording — after this, transcription is fully
offline and no audio leaves the machine.

Re-running is safe: an existing install is detected and skipped without any
network access.
"""

from __future__ import annotations

import os
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path

MODEL_NAME = "sherpa-onnx-nemo-streaming-fast-conformer-transducer-en-80ms-int8"
URL = (
    "https://github.com/k2-fsa/sherpa-onnx/releases/download/asr-models/"
    f"{MODEL_NAME}.tar.bz2"
)
APPROX_MB = 103

#: Files the sidecar needs. Presence of all four means a usable install.
REQUIRED = ("tokens.txt", "encoder", "decoder", "joiner")


def target_dir() -> Path:
    override = os.environ.get("STT_MODEL_DIR", "").strip()
    if override:
        return Path(override)
    return Path(__file__).resolve().parents[3] / "models" / "stt" / "nemo-fastconformer-80ms-int8"


def is_installed(path: Path) -> bool:
    if not path.is_dir():
        return False
    names = [p.name for p in path.iterdir() if p.is_file()]
    return all(any(name.startswith(req) for name in names) for req in REQUIRED)


def main() -> int:
    target = target_dir()
    if is_installed(target):
        size = sum(f.stat().st_size for f in target.rglob("*") if f.is_file())
        print(f"Already installed: {target} ({size / 1e6:.0f} MB)")
        return 0

    target.parent.mkdir(parents=True, exist_ok=True)
    archive = target.parent / f"{MODEL_NAME}.tar.bz2"
    print(f"Downloading NeMo streaming FastConformer EN 80ms int8 (~{APPROX_MB} MB)")
    print(f"  -> {target}")

    last = [-1]

    def report(done: int, block: int, total: int) -> None:
        if total <= 0:
            return
        step = int(min(100.0, done * block * 100.0 / total)) // 10
        if step > last[0]:
            last[0] = step
            print(f"  {step * 10}%", flush=True)

    extract_dir = target.parent / f"_extract_{MODEL_NAME}"
    try:
        urllib.request.urlretrieve(URL, archive, reporthook=report)
        if extract_dir.exists():
            shutil.rmtree(extract_dir)
        with tarfile.open(archive, "r:bz2") as tf:
            # filter="data" rejects absolute paths and symlinks escaping the
            # destination — this is a third-party archive.
            tf.extractall(extract_dir, filter="data")

        extracted = extract_dir / MODEL_NAME
        if not extracted.is_dir():
            dirs = [p for p in extract_dir.iterdir() if p.is_dir()]
            if len(dirs) != 1:
                raise RuntimeError(f"unexpected archive layout: {[p.name for p in extract_dir.iterdir()]}")
            extracted = dirs[0]

        if target.exists():
            shutil.rmtree(target)
        shutil.move(str(extracted), str(target))
    except Exception as exc:  # noqa: BLE001
        print(f"FAILED: {exc}")
        return 1
    finally:
        archive.unlink(missing_ok=True)
        shutil.rmtree(extract_dir, ignore_errors=True)

    size = sum(f.stat().st_size for f in target.rglob("*") if f.is_file())
    print(f"Installed: {target} ({size / 1e6:.0f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
