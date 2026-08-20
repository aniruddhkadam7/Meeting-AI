"""Freezes the streaming ASR sidecar into a standalone executable with
PyInstaller, for bundling into release builds of the desktop app.

Why: `packages/stt/.venv` is not relocatable — its `python.exe` hardcodes
the absolute path of the base Python install it was created from (see
`packages/stt/.venv/pyvenv.cfg`'s `home`/`executable` fields), so copying
the venv folder into an installer fails on any machine other than the one
it was created on. PyInstaller instead produces a self-contained onedir
build with its own embedded Python runtime and all of sherpa-onnx/numpy's
native dependencies, with no dependency on the target machine having
Python installed at all.

Run from `packages/stt` with the project's own venv active (or invoked
directly, as below), after `pip install pyinstaller` into that venv:

    .venv/Scripts/python.exe packages/stt/scripts/freeze_sidecar.py

Output lands in `packages/stt/dist/stt-sidecar/` (an .exe plus its
`_internal` support folder) — see `apps/desktop/src-tauri/tauri.conf.json`'s
`bundle.resources`, which packages that folder into every release build as
the `stt-sidecar` resource, and `apps/desktop/src-tauri/src/stt/sidecar.rs`'s
`frozen_sidecar_path`, which finds and runs it instead of a system Python at
app startup.

`--onedir` rather than `--onefile`: onefile self-extracts to a fresh temp
directory on every single launch, which would reintroduce the multi-second
startup delay the rest of this app's STT-prewarm work was specifically
built to eliminate — see docs/performance-tuning.md.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

STT_DIR = Path(__file__).resolve().parents[1]


def main() -> int:
    return subprocess.call(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--name",
            "stt-sidecar",
            "--onedir",
            "--noconfirm",
            "--clean",
            "--console",
            "--distpath",
            str(STT_DIR / "dist"),
            "--workpath",
            str(STT_DIR / "build"),
            "--collect-all",
            "sherpa_onnx",
            "--collect-all",
            "onnxruntime",
            str(STT_DIR / "streaming_asr_sidecar" / "sidecar.py"),
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
