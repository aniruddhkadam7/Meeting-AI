# Local RAG Service

A local-only Python/FastAPI service that turns uploaded documents (resume, job
description, project write-ups, notes) into a searchable local knowledge base,
and answers semantic search queries against it. Spawned and managed as a child
process by the desktop app (see
`apps/desktop/src-tauri/src/rag/process.rs`), the same way the PocketSphinx STT
sidecar is managed — but this one speaks plain HTTP (bound to `127.0.0.1` only)
since document upload and search are request/response operations, not a
continuous stream.

This is a **separate process from `apps/backend`** (the FastAPI analysis
service that the desktop's "Analyze Interview" button talks to). Nothing here
has an outbound HTTP client — it never uploads documents, chunks, or embeddings
anywhere, and `apps/backend` never receives them either.

## Pipeline

```
File -> Validation -> Text Extraction -> Cleaning -> Chunking -> Embedding -> Vector Store
```

- **Loaders**: `pypdf` (PDF), `python-docx` (DOCX), plain UTF-8/Latin-1 decode
  (TXT/Markdown).
- **Chunking**: heading > paragraph > sentence > hard-cutoff boundary
  preference, ~650 tokens per chunk with ~80 tokens of overlap (both
  configurable).
- **Embeddings**: `sentence-transformers/all-MiniLM-L6-v2`, run entirely
  on-CPU, no API key, no network call. See `app/embeddings.py` for why this
  model was chosen.
- **Vector store**: SQLite + the `sqlite-vec` extension (a single `.db` file
  under the user's local AppData directory — no server, no cloud). See
  `app/vector_store.py`.

## Setup

```bash
cd packages/rag
py -3 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

## Run standalone (for development/testing outside the desktop app)

```bash
python -m uvicorn app.main:app --port 8100
```

```bash
curl http://127.0.0.1:8100/health
```

## Test

```bash
pytest
```

Most tests use a fake deterministic embedding provider (`tests/conftest.py`) so
the suite runs in ~1.5s without downloading/loading the real model. Retrieval
*quality* (not just plumbing) was verified manually with the real model — see
`docs/progress.md` Step 9 for the exact test queries and results.

## Data location

Nothing is stored inside this repository. All documents, extracted text, and
the vector store live under:

```
%APPDATA%\InterviewAssistant\knowledge\
    documents\      raw uploaded files
    extracted\      cleaned extracted text
    vector_store\   knowledge.db (SQLite + sqlite-vec)
```

## Endpoints

- `GET /health`
- `POST /documents/upload` — multipart file + `document_type` form field.
- `GET /documents` — list all documents with status/chunk counts.
- `DELETE /documents/{document_id}`
- `POST /knowledge-base/clear` — removes all documents and chunks.
- `GET /knowledge-base/status` — document/chunk counts and overall status.
- `POST /search` — `{ query, top_k }` -> ranked chunks with scores.
