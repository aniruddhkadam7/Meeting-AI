"""Runs two STT engines on the same live system audio, side by side.

Point this at whatever you are actually listening to — a podcast, a recorded
interview, a meeting — and it feeds the identical sample stream to both engines
so the difference you see is the engine and nothing else.

    cargo run --bin stt_spike --manifest-path apps\\desktop\\src-tauri\\Cargo.toml -- 60 | ^
      packages\\stt-bench\\.venv\\Scripts\\python.exe ^
      packages\\stt-bench\\scripts\\ab_compare.py pocketsphinx nemo-80ms --save capture.wav

`--save` writes the captured audio to a 16 kHz mono WAV. Keep it: it turns a
one-off impression into something re-runnable, so any later engine or setting
can be scored against the same real audio instead of against a fresh take.

Both engines run on their own worker threads. The slower one falling behind
shows up in its own transcript, not in the other's.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sttbench.audio import Clip, write_wav  # noqa: E402
from sttbench.engines.base import EngineUnavailable  # noqa: E402

from run_bench import ENGINES  # noqa: E402

READ_SAMPLES = 1600  # 100 ms


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("engines", nargs=2, metavar="ENGINE", choices=sorted(ENGINES))
    parser.add_argument("--save", default=None, help="write captured audio to this WAV")
    args = parser.parse_args()

    engines = []
    for key in args.engines:
        print(f"loading {key}...", file=sys.stderr, flush=True)
        engine = ENGINES[key]()
        try:
            engine.start()
        except EngineUnavailable as exc:
            print(f"  {key} unavailable: {exc}", file=sys.stderr)
            return 1
        engines.append((key, engine))

    print("ready — both engines are receiving the same audio", file=sys.stderr)
    print("-" * 72, file=sys.stderr, flush=True)

    finals: dict[str, list[str]] = {key: [] for key, _ in engines}
    captured: list[np.ndarray] = []
    stdin = sys.stdin.buffer
    started = time.monotonic()

    try:
        while True:
            raw = stdin.read(READ_SAMPLES * 2)
            if not raw:
                break
            samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
            if args.save:
                captured.append(samples)

            for key, engine in engines:
                engine.feed_audio(samples)
                for event in engine.poll():
                    if event.is_final and event.text.strip():
                        finals[key].append(event.text.strip())
                        elapsed = event.wall_time_s - started
                        print(f"[{elapsed:6.1f}s] {key:<16} {event.text.strip()}",
                              file=sys.stderr, flush=True)
    except KeyboardInterrupt:
        pass

    for key, engine in engines:
        for event in engine.stop():
            if event.is_final and event.text.strip():
                finals[key].append(event.text.strip())

    if args.save and captured:
        path = Path(args.save)
        write_wav(path, Clip(np.concatenate(captured)))
        print(f"\naudio saved: {path}  ({sum(len(c) for c in captured) / 16000:.1f}s)",
              file=sys.stderr)

    print()
    print("=" * 72)
    print("SIDE BY SIDE")
    print("=" * 72)
    for key, _ in engines:
        text = " ".join(finals[key]).strip()
        words = len(text.split())
        print(f"\n### {key}   ({words} words, {len(finals[key])} segments)")
        print(text or "(nothing)")

    print()
    print("=" * 72)
    print("Read the two transcripts against what was actually said. Neither is")
    print("scored here — there is no ground truth for arbitrary podcast audio.")
    if args.save:
        print(f"To score properly, transcribe a short section of {args.save} by hand")
        print("and compare. That is the only way to get a real WER on this content.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
