"""Runs every candidate STT engine over the recorded corpus and reports.

    py -3 packages/stt-bench/scripts/run_bench.py
    py -3 packages/stt-bench/scripts/run_bench.py --engines pocketsphinx parakeet-240
    py -3 packages/stt-bench/scripts/run_bench.py --corpus corpus/human

Requires the corpus to have been recorded first:

    py -3 packages/stt-bench/scripts/record_corpus.py

Audio is fed to every engine at 1x real time, so a full run takes roughly
(number of engines) x (corpus duration + 2 s per sentence). Nothing here touches
the network.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sttbench import runner  # noqa: E402
from sttbench.audio import read_wav  # noqa: E402
from sttbench.engines import pocketsphinx_engine, sherpa_offline, sherpa_streaming  # noqa: E402
from sttbench.engines import whispercpp_engine  # noqa: E402
from sttbench.sentences import SENTENCES  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

#: Every candidate, in the order the report should present them: the incumbent
#: first, then rolling-window approaches, then native streaming.
ENGINES: dict[str, callable] = {
    "pocketsphinx": lambda: pocketsphinx_engine.PocketSphinxSTT(),
    "whisper-base-en": lambda: whispercpp_engine.build("base.en"),
    "whisper-small-en": lambda: whispercpp_engine.build("small.en"),
    "moonshine-base": sherpa_offline.moonshine_base_en,
    "parakeet-offline": sherpa_offline.parakeet_unified_offline,
    "zipformer-kroko": lambda: sherpa_streaming.SherpaStreamingSTT(
        sherpa_streaming.ZIPFORMER_EN_KROKO
    ),
    "nemo-80ms": lambda: sherpa_streaming.SherpaStreamingSTT(
        sherpa_streaming.NEMO_FASTCONFORMER_80
    ),
    "nemo-480ms": lambda: sherpa_streaming.SherpaStreamingSTT(
        sherpa_streaming.NEMO_FASTCONFORMER_480
    ),
    "parakeet-240ms": lambda: sherpa_streaming.SherpaStreamingSTT(
        sherpa_streaming.PARAKEET_UNIFIED_240
    ),
    "parakeet-560ms": lambda: sherpa_streaming.SherpaStreamingSTT(
        sherpa_streaming.PARAKEET_UNIFIED_560
    ),
}


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


def fmt_ms(value: float | None) -> str:
    return "     —" if value is None else f"{value:6.0f}"


def print_summary(results: list[runner.EngineResult]) -> None:
    available = [r for r in results if r.available and r.clips]
    print()
    print("=" * 118)
    print("RESULTS")
    print("=" * 118)
    header = (
        f"{'engine':<44} {'WER':>7} {'acc':>7} {'compl':>7} {'terms':>7} "
        f"{'1st ptl':>8} {'final':>8} {'ptl int':>8} {'RAM MB':>8} {'CPU%':>6}"
    )
    print(header)
    print("-" * 118)
    for r in sorted(available, key=lambda x: x.overall_wer):
        res = r.resources
        print(
            f"{r.engine_name[:44]:<44} "
            f"{r.overall_wer * 100:6.1f}% "
            f"{r.overall_accuracy * 100:6.1f}% "
            f"{r.overall_completeness * 100:6.1f}% "
            f"{r.term_recall * 100:6.1f}% "
            f"{fmt_ms(r.median_first_partial_ms)}ms "
            f"{fmt_ms(r.median_finalization_ms)}ms "
            f"{fmt_ms(r.median_partial_interval_ms)}ms "
            f"{res.get('rss_mb_delta', 0):8.0f} "
            f"{res.get('cpu_percent_mean_of_machine', 0):5.1f}%"
        )

    skipped = [r for r in results if not r.available]
    if skipped:
        print()
        print("SKIPPED")
        for r in skipped:
            print(f"  {r.engine_name[:60]:<60} {r.unavailable_reason[:80]}")

    print()
    print("TRANSCRIPTS")
    print("-" * 118)
    for r in sorted(available, key=lambda x: x.overall_wer):
        print(f"\n### {r.engine_name}   (WER {r.overall_wer * 100:.1f}%)")
        for clip in r.clips:
            flag = "ok " if clip.wer <= 0.10 else ("~  " if clip.wer <= 0.30 else "BAD")
            print(f"  [{flag}] {clip.sentence_id}  wer={clip.wer * 100:5.1f}%")
            print(f"        ref: {clip.reference}")
            print(f"        hyp: {clip.hypothesis or '(nothing)'}")
            if clip.terms_missed:
                print(f"        missed terms: {', '.join(clip.terms_missed)}")


def _run_isolated(key: str, corpus_dir: Path, gpu: bool) -> runner.EngineResult:
    """Runs one engine in a fresh interpreter and reads its result back."""
    import json
    import subprocess
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "result.json"
        cmd = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--corpus", str(corpus_dir),
            "--engines", key,
            "--out", str(out),
            "--in-process",
        ]
        if gpu:
            cmd.append("--gpu")
        proc = subprocess.run(cmd, capture_output=True, text=True)
        if not out.exists():
            tail = (proc.stderr or proc.stdout or "").strip().splitlines()[-3:]
            return runner.EngineResult(
                engine_name=key,
                strategy="",
                model_name="",
                model_size_mb=0.0,
                supports_partials=False,
                offline=True,
                notes="",
                available=False,
                unavailable_reason=f"subprocess failed: {' | '.join(tail)}",
            )
        payload = json.loads(out.read_text(encoding="utf-8"))

    entry = payload["engines"][0]
    clips = [runner.ClipResult(**c) for c in entry.pop("clips", [])]
    # Drop the derived fields save_results adds; they are recomputed as
    # properties on the reconstructed object.
    for derived in (
        "overall_wer", "overall_accuracy", "overall_completeness", "term_recall",
        "median_first_partial_ms", "median_finalization_ms", "median_partial_interval_ms",
    ):
        entry.pop(derived, None)
    return runner.EngineResult(**entry, clips=clips)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", default="corpus/human", help="directory of s1..s4 WAVs")
    parser.add_argument("--engines", nargs="*", default=None, help="subset of engine keys")
    parser.add_argument("--out", default=None, help="results JSON path")
    parser.add_argument("--gpu", action="store_true", help="also sample nvidia-smi")
    parser.add_argument(
        "--in-process",
        action="store_true",
        help=argparse.SUPPRESS,  # internal: set on the per-engine child process
    )
    args = parser.parse_args()

    corpus_dir = Path(args.corpus)
    if not corpus_dir.is_absolute():
        corpus_dir = ROOT / corpus_dir

    clips, bounds, missing = load_corpus(corpus_dir)
    if missing:
        print(f"Corpus incomplete — missing {len(missing)} file(s) in {corpus_dir}:")
        for path in missing:
            print(f"  {path.name}")
        print()
        print("Record it first:  py -3 packages/stt-bench/scripts/record_corpus.py")
        return 2

    selected = args.engines or list(ENGINES)
    unknown = [k for k in selected if k not in ENGINES]
    if unknown:
        print(f"unknown engine(s): {', '.join(unknown)}")
        print(f"available: {', '.join(ENGINES)}")
        return 2

    total_audio = sum(c.duration_s for c in clips.values())
    print(f"Corpus     : {corpus_dir}  ({len(clips)} clips, {total_audio:.1f}s of audio)")
    for sentence in SENTENCES:
        start, end = bounds[sentence.id]
        print(
            f"  {sentence.id}: {clips[sentence.id].duration_s:5.2f}s  "
            f"speech {start:.2f}s..{end:.2f}s"
        )
    print(f"Engines    : {len(selected)}")
    print(f"Pacing     : 1x real time, {runner.FEED_CHUNK_MS}ms chunks, "
          f"{runner.TRAILING_SILENCE_MS}ms trailing silence")
    print()

    results: list[runner.EngineResult] = []
    for key in selected:
        print(f"--> {key}", flush=True)
        started = time.monotonic()
        if args.in_process or len(selected) == 1:
            result = runner.run_engine(
                ENGINES[key], list(SENTENCES), clips, bounds, watch_gpu=args.gpu
            )
        else:
            # Each engine gets its own process. Python does not return freed
            # memory to the OS, so a shared process would carry the previous
            # model's footprint into the next engine's baseline — which showed
            # up as a 0 MB delta for whatever ran after a large model. Peak RSS
            # is only meaningful against a clean interpreter.
            result = _run_isolated(key, corpus_dir, args.gpu)
        results.append(result)
        if result.available:
            print(
                f"    done in {time.monotonic() - started:.1f}s  "
                f"(load {result.load_time_s:.1f}s)  WER {result.overall_wer * 100:.1f}%",
                flush=True,
            )
        else:
            print(f"    unavailable: {result.unavailable_reason}", flush=True)

    print_summary(results)

    out = Path(args.out) if args.out else ROOT / "results" / "benchmark.json"
    if not out.is_absolute():
        out = ROOT / out
    runner.save_results(results, out)
    print(f"\nRaw results: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
