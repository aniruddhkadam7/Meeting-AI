"""Freezes a torch-free build of the RAG service ("rag-lite") into a
standalone executable with PyInstaller, for bundling into release builds of
the desktop app.

Why a separate build at all: the full RAG service (`packages/rag/.venv`)
pulls in sentence-transformers/torch for semantic-search embeddings, ~800MB
— too large to bundle just so CV/JD PDF/DOCX uploads can extract text, which
`pypdf`/`python-docx` do with zero torch dependency. `app/pipeline.py`'s
`process_document` already treats an embedding `ImportError` as "no semantic
search for this document" rather than "upload failed", so a build with no
embedding libraries installed at all still fully supports document
upload/extraction — it just never populates the vector index. Uploading
still works, `GET /documents/{id}/text` still works, the setup screen's
CV/JD auto-analysis still works; only in-interview semantic search over
uploaded documents is unavailable, which is already a best-effort/non-fatal
path (see `RetrievalPlanner` on the Rust side), never a hard requirement.

Same "why PyInstaller, why --onedir" reasoning as
`packages/stt/scripts/freeze_sidecar.py` — a plain venv is not relocatable
(see `packages/rag/.venv/pyvenv.cfg`'s hardcoded absolute paths), and
--onefile's self-extraction would reintroduce real startup latency.

One-time setup (creates the torch-free build venv this script runs from):

    py -3 -m venv packages/rag/.venv-lite
    packages/rag/.venv-lite/Scripts/python.exe -m pip install -r packages/rag/requirements-lite.txt pyinstaller

Then run from `packages/rag`:

    .venv-lite/Scripts/python.exe packages/rag/scripts/freeze_rag_lite.py

Output lands in `packages/rag/dist/rag-lite/` — see
`apps/desktop/src-tauri/tauri.conf.json`'s `bundle.resources` (packaged as
the `rag-lite` resource) and `apps/desktop/src-tauri/src/rag/process.rs`'s
`frozen_rag_lite_path`, which finds and runs it instead of a system Python
at app startup.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

RAG_DIR = Path(__file__).resolve().parents[1]


def main() -> int:
    return subprocess.call(
        [
            sys.executable,
            "-m",
            "PyInstaller",
            "--name",
            "rag-lite",
            "--onedir",
            "--noconfirm",
            "--clean",
            "--console",
            "--distpath",
            str(RAG_DIR / "dist"),
            "--workpath",
            str(RAG_DIR / "build"),
            "--paths",
            str(RAG_DIR),
            "--collect-all",
            "pypdf",
            "--collect-all",
            "docx",
            "--collect-submodules",
            "uvicorn",
            "--collect-data",
            "sqlite_vec",
            "--hidden-import",
            "app.routes",
            "--hidden-import",
            "app.pipeline",
            "--hidden-import",
            "app.embeddings",
            "--hidden-import",
            "app.loaders",
            "--hidden-import",
            "app.loaders.pdf_loader",
            "--hidden-import",
            "app.loaders.docx_loader",
            "--hidden-import",
            "multipart",
            str(RAG_DIR / "run_rag.py"),
        ]
    )


if __name__ == "__main__":
    raise SystemExit(main())
