"""Phase B benchmark: measures STT latency while RAG document indexing runs
concurrently, with the throttle (packages/rag/app/throttle.py) on vs off.

Methodology: starts a document upload to a real, already-running RAG service
(127.0.0.1:8100) on a background thread — a large-enough document to keep
the embedding step busy for the STT run's duration — then immediately runs
the STT thread-sweep's single-clip harness and reports first-partial/
finalize/CPU exactly like the other STT benchmarks in this project, so the
numbers are directly comparable to the Phase A baseline.

Requires the RAG service to already be running and reachable (this script
does not spawn it, matching how the desktop app's own coordination code
never restarts RAG either):

    py -3 -m uvicorn app.main:app --port 8100   # from packages/rag/, in another terminal

Usage:
    py -3 packages/stt-bench/scripts/phase_b_contention_bench.py --throttle off
    py -3 packages/stt-bench/scripts/phase_b_contention_bench.py --throttle on
"""

from __future__ import annotations

import argparse
import json
import sys
import threading
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sttbench import runner  # noqa: E402
from sttbench.audio import read_wav  # noqa: E402
from sttbench.engines import sherpa_streaming  # noqa: E402
from sttbench.sentences import SENTENCES  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAG_BASE = "http://127.0.0.1:8100"

# A large-enough synthetic document that embedding takes several seconds —
# long enough to overlap the ~1s STT clip runs below. Repeated paragraphs so
# chunking produces plenty of chunks to embed (~650-token chunks, so this
# needs to be sized well past one chunk).
_DOC_PARAGRAPH = (
    "Smallbird is a local-first meeting and interview assistant. It captures "
    "system audio and transcribes it locally using a streaming speech "
    "recognition model, then retrieves relevant context from uploaded "
    "documents to help answer questions during a live interview. "
) * 8
_DOCUMENT_TEXT = (_DOC_PARAGRAPH + "\n\n") * 40  # ~40 paragraphs of repeated text


def set_rag_throttle(active: bool) -> None:
    req = urllib.request.Request(
        f"{RAG_BASE}/internal/throttle",
        data=json.dumps({"active": active}).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        resp.read()


def upload_document_blocking() -> float:
    """Uploads the synthetic document via multipart/form-data (stdlib only,
    no requests dependency) and returns wall-clock seconds taken. Content
    is made unique per call (a random prefix) so the RAG service's
    content-hash deduplication (packages/rag/app/pipeline.py's
    find_document_by_hash) never short-circuits a repeat benchmark run into
    a 0-second no-op."""
    import uuid

    unique_prefix = f"[bench run {uuid.uuid4().hex}]\n\n"
    document_text = unique_prefix + _DOCUMENT_TEXT

    boundary = uuid.uuid4().hex
    body = []
    body.append(f"--{boundary}".encode())
    body.append(b'Content-Disposition: form-data; name="file"; filename="bench.txt"')
    body.append(b"Content-Type: text/plain")
    body.append(b"")
    body.append(document_text.encode())
    body.append(f"--{boundary}".encode())
    body.append(b'Content-Disposition: form-data; name="document_type"')
    body.append(b"")
    body.append(b"OTHER")
    body.append(f"--{boundary}--".encode())
    body.append(b"")
    payload = b"\r\n".join(body)

    req = urllib.request.Request(
        f"{RAG_BASE}/documents/upload",
        data=payload,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    started = time.perf_counter()
    with urllib.request.urlopen(req, timeout=60) as resp:
        resp.read()
    return time.perf_counter() - started


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--throttle", choices=["on", "off"], required=True)
    parser.add_argument("--corpus", default="corpus/synthetic")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()

    corpus_dir = Path(args.corpus)
    if not corpus_dir.is_absolute():
        corpus_dir = ROOT / corpus_dir

    clips, bounds = {}, {}
    for s in SENTENCES:
        clip = read_wav(corpus_dir / f"{s.id}.wav")
        clips[s.id] = clip
        bounds[s.id] = runner.speech_bounds(clip)

    set_rag_throttle(args.throttle == "on")
    print(f"RAG throttle set to: {args.throttle}")

    upload_result: dict = {}

    def do_upload():
        upload_result["seconds"] = upload_document_blocking()

    upload_thread = threading.Thread(target=do_upload, daemon=True)
    upload_thread.start()
    time.sleep(0.3)  # let the upload actually start (extraction/chunking) before STT begins

    cfg = sherpa_streaming.NEMO_FASTCONFORMER_80
    stt_result = runner.run_engine(
        lambda: sherpa_streaming.SherpaStreamingSTT(cfg), list(SENTENCES), clips, bounds
    )

    upload_thread.join(timeout=60)
    set_rag_throttle(False)  # always clean up, regardless of what was tested

    print(f"\n=== Phase B contention benchmark (throttle={args.throttle}) ===")
    print(f"RAG upload+embed wall time : {upload_result.get('seconds', float('nan')):.2f}s")
    print(f"STT 1st partial (median)   : {stt_result.median_first_partial_ms:.0f}ms")
    print(f"STT finalize (median)      : {stt_result.median_finalization_ms:.0f}ms")
    print(f"STT WER                    : {stt_result.overall_wer*100:.1f}%")
    print(f"STT CPU % of machine       : {stt_result.resources['cpu_percent_mean_of_machine']:.1f}%")
    print(f"STT CPU peak % of machine  : {stt_result.resources['cpu_percent_peak_of_machine']:.1f}%")

    out = Path(args.out) if args.out else ROOT / "results" / f"phase_b_throttle_{args.throttle}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            {
                "throttle": args.throttle,
                "rag_upload_seconds": upload_result.get("seconds"),
                "stt_first_partial_ms": stt_result.median_first_partial_ms,
                "stt_finalize_ms": stt_result.median_finalization_ms,
                "stt_wer": stt_result.overall_wer,
                "stt_resources": stt_result.resources,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\nRaw results: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
