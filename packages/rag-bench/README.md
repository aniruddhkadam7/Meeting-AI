# RAG benchmark

Standalone harness for sweeping REDLY's local RAG embedding/index/search
pipeline across torch thread counts and encode batch sizes. Isolated from
`packages/rag` the same way `packages/stt-bench` is isolated from
`apps/desktop` — it imports `packages/rag`'s real `app.embeddings` /
`app.vector_store` modules directly (no HTTP layer, no uvicorn) but never
modifies any file under `packages/rag`. Deleting this directory cannot break
the RAG service.

Built to validate (or correct) the hardware-adaptive tier table in
`apps/desktop/src-tauri/src/hardware/manager.rs` — see
`docs/performance-tuning.md` for the results and what they changed.

Everything runs locally against synthetic chunk text; no document content or
network access beyond the RAG service's own one-time model download (which
must already be cached — this harness does not trigger it if missing).

## Setup

Reuses `packages/rag`'s own venv (same production model, same dependency
versions) plus `psutil` for CPU/RAM sampling:

```powershell
..\rag\.venv\Scripts\python.exe -m pip install psutil
```

## Running

```powershell
..\rag\.venv\Scripts\python.exe bench.py
..\rag\.venv\Scripts\python.exe bench.py --batch 8 16 32 64 --threads 1 2 4 8
..\rag\.venv\Scripts\python.exe bench.py --num-chunks 500
```

Each (batch size, thread count) configuration runs in its own subprocess —
matching `stt-bench`'s isolation pattern — so torch's thread count (which
some backends cannot change after the first op) never leaks between
configurations, and RSS is measured against a clean interpreter baseline.

Reports, per configuration: model load time, embed time (total and per
synthetic chunk), index time, and search latency (p50/p99 over five fixed
queries), plus RSS delta and CPU%-of-process during embedding.

## Layout

```
bench.py       everything — sweep driver, single-config runner, report
results/       raw JSON from the last sweep (gitignored contents, kept as
               evidence for docs/performance-tuning.md)
```
