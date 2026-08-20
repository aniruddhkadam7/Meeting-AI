# Smallbird Backend

FastAPI service that receives a **finalized interview transcript** from the desktop
app after the user explicitly clicks "Analyze Interview", and returns an analysis
result. This process never captures audio and never runs speech-to-text — that all
happens locally in the Tauri/Rust desktop app (WASAPI + PocketSphinx). See
`../../docs/architecture.md` for the full local/backend boundary.

Phase 1 status: the analysis endpoint returns a deterministic **mock** result (all
scores are 0, all lists are empty). No LLM or RAG is connected yet.

## Setup

```bash
cd apps/backend
py -3 -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
```

## Run

```bash
python -m uvicorn app.main:app --reload --port 8000
```

Then check:

```bash
curl http://127.0.0.1:8000/health
```

should return:

```json
{"status": "ok", "service": "smallbird-backend"}
```

## Test

```bash
pytest
```

## Endpoints

- `GET /health` — liveness check, used by the desktop app to show backend
  connection status.
- `POST /api/v1/interviews/analyze` — accepts a finalized transcript (+ optional
  role/company/job description/candidate context) and returns a mock analysis.
  Never accepts audio.
