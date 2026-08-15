"""Local RAG service entrypoint.

A separate process from apps/backend (the FastAPI analysis service) — this is
the "local service/module" the Step 9 spec calls for, kept entirely out of the
network-facing analysis backend. Binds to 127.0.0.1 only and is spawned/managed
by the Tauri desktop app as a child process, the same way the PocketSphinx STT
sidecar is (see apps/desktop/src-tauri/src/stt/sidecar.rs for that pattern; the
RAG service equivalent is apps/desktop/src-tauri/src/rag/sidecar.rs).

Nothing in this process has an outbound HTTP client — it never uploads
documents, chunks, or embeddings anywhere. It only extracts, chunks, embeds,
indexes, and searches, all against local files under the user's AppData
directory (see core/config.py).
"""

from __future__ import annotations

import logging

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.core.config import get_settings

settings = get_settings()

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("rag")

app = FastAPI(title="Interview Assistant Local RAG Service", version="0.1.0")

# Same reasoning as apps/backend: an explicit allowlist, never "*", even though
# this service only ever binds to localhost.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:1420",
        "http://127.0.0.1:1420",
        "tauri://localhost",
        "https://tauri.localhost",
    ],
    allow_credentials=False,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type"],
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    first_error = exc.errors()[0] if exc.errors() else {}
    field = ".".join(str(loc) for loc in first_error.get("loc", []) if loc != "body")
    detail = first_error.get("msg", "Invalid request")
    message = f"{field}: {detail}" if field else detail
    return JSONResponse(status_code=422, content={"error": {"code": "VALIDATION_ERROR", "message": message}})


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    logger.exception("[RAG] unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred."}},
    )


from app.routes import router  # noqa: E402  (after app/exception handlers defined)

app.include_router(router)
