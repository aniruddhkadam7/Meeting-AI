"""Entry point for the frozen "rag-lite" build bundled into desktop release
installers (see scripts/freeze_rag_lite.py and
apps/desktop/src-tauri/src/rag/process.rs).

Equivalent to `python -m uvicorn app.main:app --host 127.0.0.1 --port <port>`
(what the dev-tree venv path still runs directly) — but as a plain script
PyInstaller can freeze on its own terms, importing the ASGI app object and
calling `uvicorn.run()` ourselves rather than relying on `-m uvicorn`'s own
CLI/plugin dynamic-import machinery, which does not freeze reliably.
"""

from __future__ import annotations

import os

import uvicorn

from app.main import app

if __name__ == "__main__":
    port = int(os.environ.get("RAG_PORT", "8100"))
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
