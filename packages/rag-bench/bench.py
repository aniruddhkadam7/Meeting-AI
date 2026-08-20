"""Benchmarks Smallbird's local RAG pipeline (embedding + sqlite-vec search)
against different torch-thread-count / encode-batch-size configurations, to
correct or confirm the adaptive-performance-engine's provisional
RAG_EMBED_BATCH_SIZE / RAG_TORCH_THREADS tier values
(apps/desktop/src-tauri/src/hardware/manager.rs) with real measurements
instead of assumptions.

Isolated from packages/rag exactly like packages/stt-bench is isolated from
apps/desktop (see packages/stt-bench/README.md) — this imports packages/rag's
real app.embeddings / app.vector_store / app.chunking modules directly
in-process (no HTTP layer, no uvicorn) so a config sweep does not need to
restart a server between configurations. It never modifies any file under
packages/rag; RAG_EMBED_BATCH_SIZE/RAG_TORCH_THREADS are not real env vars
yet (that plumbing is Milestone 5) — this script sets torch's thread count
directly via torch.set_num_threads() and passes batch_size straight to
SentenceTransformer.encode(), which is exactly what that future plumbing
will do.

Each configuration runs in its own subprocess (matching stt-bench's
isolation pattern) so CPU/RAM measurements start from a clean interpreter
baseline and torch's thread count — which cannot be changed after the first
op on some backends — never leaks between configurations.

    packages/rag/.venv/Scripts/python.exe packages/rag-bench/bench.py
    packages/rag/.venv/Scripts/python.exe packages/rag-bench/bench.py --batch 8 16 32 64 --threads 1 2 4 8
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
RAG_APP_DIR = ROOT / "rag"

DEFAULT_BATCH_SIZES = [8, 16, 32, 64]
DEFAULT_THREAD_COUNTS = [1, 2, 4, 8]

#: Realistic chunk-sized text (roughly the 650-token chunk size
#: packages/rag/app/core/config.py's CHUNK_SIZE_TOKENS defaults to), repeated
#: to build a corpus large enough that indexing/search latency is measurable
#: rather than dominated by Python call overhead.
_SAMPLE_CHUNK = (
    "Smallbird is a local-first meeting and interview assistant. It captures "
    "system audio and microphone input via WASAPI, transcribes it locally "
    "using a streaming speech recognition model, and retrieves relevant "
    "context from the user's uploaded documents to help answer questions "
    "during a live interview, sales call, or consulting engagement. All "
    "speech-to-text and retrieval computation happens on the local machine; "
    "only the final language-model call for generating an answer goes to "
    "Smallbird's cloud backend, and it never receives raw audio. The knowledge "
    "base is stored in a local SQLite database with a vector search "
    "extension, so document upload, chunking, embedding, and search all "
    "happen without any network access after the embedding model itself "
    "has been downloaded once. "
) * 3

_SAMPLE_QUERIES = [
    "How does Smallbird capture system audio?",
    "What happens to my documents when I upload them?",
    "Is any of my audio sent to the cloud?",
    "How does the retrieval system find relevant context?",
    "What database does the knowledge base use?",
]


def _build_test_chunks(n: int):
    from app.models import Chunk, DocumentType

    return [
        Chunk(
            chunk_id=f"bench-chunk-{i}",
            document_id="bench-doc",
            document_type=DocumentType.OTHER,
            filename="bench.txt",
            chunk_index=i,
            text=f"[chunk {i}] {_SAMPLE_CHUNK}",
        )
        for i in range(n)
    ]


def _run_in_process(batch_size: int, torch_threads: int, num_chunks: int) -> dict:
    """Runs one (batch_size, torch_threads) configuration against a fresh
    in-memory-ish vector store (temp file, deleted after) and returns
    load/embed/index/search latency + RSS/CPU. Imported here, not at module
    scope, so the parent process (which sweeps configs via subprocess) never
    itself imports torch/sentence-transformers."""
    import os
    import tempfile as _tempfile

    sys.path.insert(0, str(RAG_APP_DIR))
    os.chdir(RAG_APP_DIR)

    import psutil
    import torch

    torch.set_num_threads(torch_threads)

    proc = psutil.Process()
    baseline_rss_mb = proc.memory_info().rss / 1e6
    proc.cpu_percent(None)  # prime

    from app.embeddings import LocalEmbeddingProvider
    from app.vector_store import VectorStore

    provider = LocalEmbeddingProvider("sentence-transformers/all-MiniLM-L6-v2", 384)

    load_started = time.perf_counter()
    provider._ensure_loaded()  # noqa: SLF001 — deliberately isolating load time
    load_s = time.perf_counter() - load_started

    chunks = _build_test_chunks(num_chunks)
    texts = [c.text for c in chunks]

    proc.cpu_percent(None)  # reset after load spike, mirrors stt-bench's resume()
    embed_started = time.perf_counter()
    import numpy as np  # noqa: F401 — provider.embed already imports what it needs

    model = provider._ensure_loaded()  # noqa: SLF001
    vectors = model.encode(texts, convert_to_numpy=True, show_progress_bar=False, batch_size=batch_size)
    embeddings = [v.tolist() for v in vectors]
    embed_s = time.perf_counter() - embed_started
    embed_cpu_pct = proc.cpu_percent(None)

    with _tempfile.TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "bench.db"
        store = VectorStore(db_path, 384)

        index_started = time.perf_counter()
        store.insert_chunks(chunks, embeddings)
        index_s = time.perf_counter() - index_started

        query_vectors = model.encode(_SAMPLE_QUERIES, convert_to_numpy=True, show_progress_bar=False)
        search_latencies_ms = []
        for qv in query_vectors:
            t0 = time.perf_counter()
            store.search(qv.tolist(), top_k=5)
            search_latencies_ms.append((time.perf_counter() - t0) * 1000.0)

        # Must close before the TemporaryDirectory context tries to delete
        # bench.db, or Windows' file locking raises PermissionError on rmtree.
        store.close()

    peak_rss_mb = proc.memory_info().rss / 1e6

    search_latencies_ms.sort()
    p50 = search_latencies_ms[len(search_latencies_ms) // 2]
    p99_index = min(len(search_latencies_ms) - 1, int(0.99 * (len(search_latencies_ms) - 1)))
    p99 = search_latencies_ms[p99_index]

    return {
        "batch_size": batch_size,
        "torch_threads": torch_threads,
        "num_chunks": num_chunks,
        "load_s": round(load_s, 2),
        "embed_s": round(embed_s, 3),
        "embed_ms_per_chunk": round((embed_s * 1000.0) / num_chunks, 2),
        "embed_cpu_percent_of_process": round(embed_cpu_pct, 1),
        "index_s": round(index_s, 3),
        "search_p50_ms": round(p50, 2),
        "search_p99_ms": round(p99, 2),
        "rss_mb_baseline": round(baseline_rss_mb, 1),
        "rss_mb_peak": round(peak_rss_mb, 1),
        "rss_mb_delta": round(max(0.0, peak_rss_mb - baseline_rss_mb), 1),
    }


def _run_isolated(batch_size: int, torch_threads: int, num_chunks: int) -> dict:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "result.json"
        cmd = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--in-process",
            "--batch-size", str(batch_size),
            "--torch-threads", str(torch_threads),
            "--num-chunks", str(num_chunks),
            "--out", str(out),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, cwd=str(Path(__file__).resolve().parent))
        if not out.exists():
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-8:]
            return {
                "batch_size": batch_size,
                "torch_threads": torch_threads,
                "available": False,
                "unavailable_reason": " | ".join(tail),
            }
        payload = json.loads(out.read_text(encoding="utf-8"))
        payload["available"] = True
        return payload


def print_summary(rows: list[dict]) -> None:
    print()
    print("=" * 118)
    print("RAG EMBED/INDEX/SEARCH SWEEP — sentence-transformers/all-MiniLM-L6-v2 (production model)")
    print("=" * 118)
    header = (
        f"{'batch':>6} {'threads':>8} {'load s':>7} {'embed s':>8} "
        f"{'ms/chunk':>9} {'index s':>8} {'search p50':>11} {'search p99':>11} "
        f"{'RAM MB':>8} {'CPU% proc':>10}"
    )
    print(header)
    print("-" * 118)
    for r in rows:
        if not r.get("available", True):
            print(f"{r['batch_size']:>6} {r['torch_threads']:>8}   unavailable: {r.get('unavailable_reason', '')[:80]}")
            continue
        print(
            f"{r['batch_size']:>6} {r['torch_threads']:>8} "
            f"{r['load_s']:7.1f} {r['embed_s']:8.2f} "
            f"{r['embed_ms_per_chunk']:9.2f} {r['index_s']:8.3f} "
            f"{r['search_p50_ms']:10.2f}ms {r['search_p99_ms']:10.2f}ms "
            f"{r['rss_mb_delta']:8.0f} {r['embed_cpu_percent_of_process']:9.1f}%"
        )
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--batch", nargs="*", type=int, default=None, dest="batch_sizes")
    parser.add_argument("--threads", nargs="*", type=int, default=None, dest="thread_counts")
    parser.add_argument("--num-chunks", type=int, default=200, help="synthetic chunks to embed/index")
    parser.add_argument("--out", default=None)
    parser.add_argument("--in-process", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--batch-size", type=int, default=None, help=argparse.SUPPRESS)
    parser.add_argument("--torch-threads", type=int, default=None, help=argparse.SUPPRESS)
    args = parser.parse_args()

    if args.in_process:
        result = _run_in_process(args.batch_size, args.torch_threads, args.num_chunks)
        out = Path(args.out) if args.out else Path(__file__).resolve().parent / "results" / "child.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2), encoding="utf-8")
        return 0

    batch_sizes = args.batch_sizes or DEFAULT_BATCH_SIZES
    thread_counts = args.thread_counts or DEFAULT_THREAD_COUNTS

    print(f"Model      : sentence-transformers/all-MiniLM-L6-v2 (production, same as packages/rag)")
    print(f"Chunks     : {args.num_chunks} synthetic chunks (~650-token-scale text)")
    print(f"Batch sizes: {batch_sizes}")
    print(f"Threads    : {thread_counts}")
    print()

    rows: list[dict] = []
    for threads in thread_counts:
        for batch in batch_sizes:
            print(f"--> batch={batch} threads={threads}", flush=True)
            row = _run_isolated(batch, threads, args.num_chunks)
            rows.append(row)
            if row.get("available", True):
                print(
                    f"    embed {row['embed_ms_per_chunk']}ms/chunk, "
                    f"search p50 {row['search_p50_ms']}ms, RSS +{row['rss_mb_delta']}MB",
                    flush=True,
                )
            else:
                print(f"    unavailable: {row.get('unavailable_reason')}", flush=True)

    print_summary(rows)

    out = Path(args.out) if args.out else Path(__file__).resolve().parent / "results" / "sweep.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"rows": rows}, indent=2), encoding="utf-8")
    print(f"Raw results: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
