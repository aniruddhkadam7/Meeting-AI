"""Sweeps STT_NUM_THREADS for the production nemo-80ms engine to find whether
WhitedotAI's hardcoded DEFAULT_NUM_THREADS=4 (packages/stt/streaming_asr_sidecar/
sidecar.py) is actually the right value on this machine, and whether a higher
value (the adaptive-performance-engine's provisional HIGH_PERFORMANCE tier
proposes 6) is justified by real latency numbers rather than assumed.

Each thread count runs in its own subprocess (matching run_bench.py's
--in-process isolation pattern) so CPU/RAM numbers are measured against a
clean interpreter baseline rather than carrying over state from the previous
thread count's run.

    py -3 packages/stt-bench/scripts/run_thread_sweep.py
    py -3 packages/stt-bench/scripts/run_thread_sweep.py --threads 1 2 4 6 8
    py -3 packages/stt-bench/scripts/run_thread_sweep.py --corpus corpus/synthetic

This does not touch the network and does not modify any file the production
app reads — it points STT_MODEL_DIR at the same on-disk model WhitedotAI ships
(models/stt/nemo-fastconformer-80ms-int8, verified byte-identical to the
stt-bench copy at models/stt-bench/nemo-fastconformer-80ms) but never writes
to apps/desktop or packages/stt.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sttbench import runner  # noqa: E402
from sttbench.audio import read_wav  # noqa: E402
from sttbench.sentences import SENTENCES  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_THREADS = [1, 2, 4, 6, 8]


def load_corpus(corpus_dir: Path):
    clips, bounds, missing = {}, {}, []
    for sentence in SENTENCES:
        path = corpus_dir / f"{sentence.id}.wav"
        if not path.exists():
            missing.append(path)
            continue
        clip = read_wav(path)
        clips[sentence.id] = clip
        bounds[sentence.id] = runner.speech_bounds(clip)
    return clips, bounds, missing


def _run_one_thread_count(num_threads: int, corpus_dir: Path, gpu: bool) -> dict:
    """Runs the nemo-80ms engine at a fixed num_threads in a fresh
    interpreter (subprocess), same isolation reasoning as run_bench.py's
    _run_isolated: Python does not return freed memory to the OS, so a
    shared process would carry the previous thread count's model footprint
    into the next one's RSS baseline."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "result.json"
        cmd = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--corpus", str(corpus_dir),
            "--threads", str(num_threads),
            "--out", str(out),
            "--in-process",
        ]
        if gpu:
            cmd.append("--gpu")
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if not out.exists():
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-5:]
            return {
                "num_threads": num_threads,
                "available": False,
                "unavailable_reason": f"subprocess failed: {' | '.join(tail)}",
            }
        payload = json.loads(out.read_text(encoding="utf-8"))
        return payload["result"]


def _run_in_process(num_threads: int, corpus_dir: Path, gpu: bool) -> dict:
    from sttbench.engines import sherpa_streaming

    clips, bounds, missing = load_corpus(corpus_dir)
    if missing:
        return {
            "num_threads": num_threads,
            "available": False,
            "unavailable_reason": f"corpus incomplete: missing {len(missing)} file(s)",
        }

    config = sherpa_streaming.StreamingConfig(
        model_key="nemo-fastconformer-80ms",
        display_name=f"nemo-80ms (threads={num_threads})",
        num_threads=num_threads,
    )
    result = runner.run_engine(
        lambda: sherpa_streaming.SherpaStreamingSTT(config),
        list(SENTENCES),
        clips,
        bounds,
        watch_gpu=gpu,
    )
    return {
        "num_threads": num_threads,
        "available": result.available,
        "unavailable_reason": result.unavailable_reason,
        "load_time_s": result.load_time_s,
        "overall_wer": result.overall_wer,
        "median_first_partial_ms": result.median_first_partial_ms,
        "median_finalization_ms": result.median_finalization_ms,
        "median_partial_interval_ms": result.median_partial_interval_ms,
        "max_feed_block_ms": result.max_feed_block_ms,
        "resources": result.resources,
    }


def fmt_ms(value) -> str:
    return "     —" if value is None else f"{value:6.0f}"


def print_summary(rows: list[dict]) -> None:
    print()
    print("=" * 118)
    print("STT_NUM_THREADS SWEEP — nemo-80ms (production model)")
    print("=" * 118)
    header = (
        f"{'threads':>7} {'load s':>7} {'WER':>7} "
        f"{'1st ptl':>8} {'final':>8} {'ptl int':>8} "
        f"{'RAM MB':>8} {'CPU% mach':>10} {'CPU% peak':>10}"
    )
    print(header)
    print("-" * 118)
    for r in rows:
        if not r.get("available", True):
            print(f"{r['num_threads']:>7}   unavailable: {r.get('unavailable_reason', '')[:90]}")
            continue
        res = r.get("resources", {})
        print(
            f"{r['num_threads']:>7} "
            f"{r.get('load_time_s', 0):7.1f} "
            f"{r.get('overall_wer', 0) * 100:6.1f}% "
            f"{fmt_ms(r.get('median_first_partial_ms'))}ms "
            f"{fmt_ms(r.get('median_finalization_ms'))}ms "
            f"{fmt_ms(r.get('median_partial_interval_ms'))}ms "
            f"{res.get('rss_mb_delta', 0):8.0f} "
            f"{res.get('cpu_percent_mean_of_machine', 0):9.1f}% "
            f"{res.get('cpu_peak_of_machine', res.get('cpu_percent_peak_of_machine', 0)):9.1f}%"
        )
    print()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", default="corpus/synthetic", help="directory of s1..s4 WAVs")
    parser.add_argument("--threads", nargs="*", type=int, default=None, help="thread counts to sweep")
    parser.add_argument("--out", default=None, help="results JSON path")
    parser.add_argument("--gpu", action="store_true", help="also sample nvidia-smi")
    parser.add_argument(
        "--in-process",
        action="store_true",
        help=argparse.SUPPRESS,  # internal: set on the per-thread-count child process
    )
    args = parser.parse_args()

    corpus_dir = Path(args.corpus)
    if not corpus_dir.is_absolute():
        corpus_dir = ROOT / corpus_dir

    if args.in_process:
        # Single-thread-count child: run one config, write result, exit.
        num_threads = args.threads[0] if args.threads else DEFAULT_THREADS[0]
        result = _run_in_process(num_threads, corpus_dir, args.gpu)
        out = Path(args.out) if args.out else ROOT / "results" / "thread_sweep_child.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"result": result}, indent=2), encoding="utf-8")
        return 0

    thread_counts = args.threads or DEFAULT_THREADS
    print(f"Corpus     : {corpus_dir}")
    print(f"Threads    : {thread_counts}")
    print(f"Model      : nemo-fastconformer-80ms (production int8, same as models/stt/)")
    print()

    rows: list[dict] = []
    for n in thread_counts:
        print(f"--> STT_NUM_THREADS={n}", flush=True)
        row = _run_one_thread_count(n, corpus_dir, args.gpu)
        rows.append(row)
        if row.get("available", True):
            print(
                f"    done — 1st partial {fmt_ms(row.get('median_first_partial_ms'))}ms, "
                f"finalize {fmt_ms(row.get('median_finalization_ms'))}ms, "
                f"CPU {row.get('resources', {}).get('cpu_percent_mean_of_machine', 0):.1f}% of machine",
                flush=True,
            )
        else:
            print(f"    unavailable: {row.get('unavailable_reason')}", flush=True)

    print_summary(rows)

    out = Path(args.out) if args.out else ROOT / "results" / "thread_sweep.json"
    if not out.is_absolute():
        out = ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"rows": rows}, indent=2), encoding="utf-8")
    print(f"Raw results: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
