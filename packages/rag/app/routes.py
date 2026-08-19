from __future__ import annotations

import logging
import re
from dataclasses import asdict
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, Field

from app.core.config import get_settings
from app.models import DocumentType
from app.pipeline import DocumentTooLargeError
from app.state import get_knowledge_base, get_retriever
from app import throttle

logger = logging.getLogger("rag.api")

router = APIRouter()

# Matches app.models.new_id("doc") exactly — rejecting anything else before it
# ever reaches a filesystem path join or glob() pattern (see get_document_text
# and delete_document below).
_DOCUMENT_ID_RE = re.compile(r"^doc_[0-9a-f]{16}$")


def _validate_document_id(document_id: str) -> str:
    if not _DOCUMENT_ID_RE.match(document_id):
        raise HTTPException(status_code=404, detail="document not found")
    return document_id


# Bounds an otherwise-unvalidated free-form field (see app.agents::new_id in
# the Rust side, "agent-<hex>-<hex>") so it can't be used to smuggle an
# arbitrarily long string into SQL params or log lines.
_MAX_AGENT_ID_LENGTH = 128


@router.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "whitedotai-rag"}


class ThrottleRequest(BaseModel):
    active: bool


@router.post("/internal/throttle")
def set_throttle(request: ThrottleRequest) -> dict:
    """Internal-only coordination endpoint (STT/RAG scheduling, Phase B —
    see app/throttle.py's module doc) — not part of the RAG service's public
    document/search API, called only by the desktop app's own Rust process
    on localhost, never by the frontend directly. `active=True` must be
    refreshed periodically or it auto-expires (dead-man's-switch, see
    throttle.py) so a crashed STT session can never permanently starve
    indexing."""
    throttle.set_active(request.active)
    return {"active": throttle.is_active()}


@router.post("/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    document_type: DocumentType = Form(...),
    agent_id: Optional[str] = Form(default=None, max_length=_MAX_AGENT_ID_LENGTH),
) -> dict:
    data = await file.read()
    logger.info(
        "[UPLOAD] filename=%s size=%d type=%s agent_id=%s",
        file.filename, len(data), document_type.value, agent_id or "-",
    )

    kb = get_knowledge_base()
    try:
        metadata = kb.process_document(file.filename or "unnamed", data, document_type, agent_id=agent_id)
    except DocumentTooLargeError as exc:
        raise HTTPException(status_code=413, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return asdict(metadata) | {
        "document_type": metadata.document_type.value,
        "status": metadata.status.value,
    }


@router.get("/documents")
def list_documents(agent_id: Optional[str] = Query(default=None, max_length=_MAX_AGENT_ID_LENGTH)) -> dict:
    kb = get_knowledge_base()
    documents = kb.list_documents(agent_id=agent_id)
    return {
        "documents": [
            asdict(doc) | {"document_type": doc.document_type.value, "status": doc.status.value}
            for doc in documents
        ]
    }


@router.get("/documents/{document_id}/text")
def get_document_text(document_id: str) -> dict:
    """Returns the cleaned, extracted plain text for a document once
    processing has reached READY (or later). Used by the New Interview setup
    page to feed an uploaded PDF/DOCX's real text into the auto-analysis
    summary, instead of only being able to analyze pasted text — this reuses
    the extraction the upload pipeline already did rather than re-parsing the
    file. Returns 404 while extraction is still in progress or if it failed,
    so the caller can treat "not ready yet" and "no such document" the same
    way (poll or give up).
    """
    document_id = _validate_document_id(document_id)
    settings = get_settings()
    extracted_path = settings.extracted_dir / f"{document_id}.txt"
    if not extracted_path.exists():
        raise HTTPException(status_code=404, detail="document text not available")
    return {"document_id": document_id, "text": extracted_path.read_text(encoding="utf-8")}


@router.delete("/documents/{document_id}")
def delete_document(document_id: str) -> dict:
    document_id = _validate_document_id(document_id)
    kb = get_knowledge_base()
    kb.delete_document(document_id)
    return {"deleted": document_id}


@router.post("/knowledge-base/clear")
def clear_knowledge_base(agent_id: Optional[str] = Query(default=None, max_length=_MAX_AGENT_ID_LENGTH)) -> dict:
    kb = get_knowledge_base()
    kb.clear_all(agent_id=agent_id)
    return {"cleared": True}


@router.get("/knowledge-base/status")
def knowledge_base_status(agent_id: Optional[str] = Query(default=None, max_length=_MAX_AGENT_ID_LENGTH)) -> dict:
    kb = get_knowledge_base()
    return kb.knowledge_base_status(agent_id=agent_id)


class SearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=20)
    agent_id: Optional[str] = Field(default=None, max_length=_MAX_AGENT_ID_LENGTH)


@router.post("/search")
def search(request: SearchRequest) -> dict:
    retriever = get_retriever()
    results, latency_ms = retriever.search(request.query, request.top_k, agent_id=request.agent_id)
    return {
        "results": [
            {
                "chunk_id": r.chunk_id,
                "score": r.score,
                "text": r.text,
                "metadata": {"filename": r.filename, "document_type": r.document_type.value},
            }
            for r in results
        ],
        "latency_ms": round(latency_ms, 2),
    }
