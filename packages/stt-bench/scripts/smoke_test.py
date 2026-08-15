"""Harness self-check: proves an engine really streams before we trust its numbers.

Feeds a WAV at 1x real time through one engine and prints every partial as it
arrives, with the wall-clock offset at which it appeared. If the partials show
up progressively while audio is still being fed, the engine is genuinely
incremental. If they all appear at the end, it is not — no matter what its
documentation claims.

    py -3 packages/stt-bench/scripts/smoke_test.py parakeet-240ms
    py -3 packages/stt-bench/scripts/smoke_test.py zipformer-kroko --wav path/to.wav
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sttbench import models  # noqa: E402
from sttbench.audio import Clip, chunk, pad_silence, read_wav  # noqa: E402
from sttbench.runner import FEED_CHUNK_MS  # noqa: E402

from run_bench import ENGINES  # noqa: E402


def default_wav() -> Path:
    path = models.model_path("parakeet-unified-streaming-240ms") / "test_wavs" / "0.wav"
    if path.exists():
        return path
    raise SystemExit("no default test wav found; pass --wav")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("engine", choices=sorted(ENGINES))
    parser.add_argument("--wav", default=None)
    args = parser.parse_args()

    wav = Path(args.wav) if args.wav else default_wav()
    clip = read_wav(wav)
    print(f"engine : {args.engine}")
    print(f"wav    : {wav.name}  ({clip.duration_s:.2f}s)")
    print()

    engine = ENGINES[args.engine]()
    load_started = time.monotonic()
    engine.start()
    print(f"model loaded in {time.monotonic() - load_started:.2f}s")
    print(f"{'audio':>7} {'wall':>7}  event")
    print("-" * 78)

    padded = pad_silence(clip, 1500)
    t0 = time.monotonic()
    audio_time = 0.0
    max_feed_ms = 0.0

    def show(events):
        for e in events:
            wall = e.wall_time_s - t0
            tag = "FINAL  " if e.is_final else "partial"
            print(f"{e.audio_time_s:6.2f}s {wall:6.2f}s  {tag} {e.text}")

    for block in chunk(padded, FEED_CHUNK_MS):
        before = time.monotonic()
        engine.feed_audio(block)
        max_feed_ms = max(max_feed_ms, (time.monotonic() - before) * 1000.0)
        show(engine.poll())
        audio_time += len(block) / 16000.0
        sleep_for = (t0 + audio_time) - time.monotonic()
        if sleep_for > 0:
            time.sleep(sleep_for)
    show(engine.stop())

    print("-" * 78)
    print(f"slowest feed_audio() call: {max_feed_ms:.2f}ms "
          f"({'OK — would not stall the UI' if max_feed_ms < 10 else 'WARNING — blocking'})")
    print(f"final text: {engine.get_final()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
