"""Live STT spike: continuous loopback audio in, interim and final text out.

This is the demonstration the spike exists to produce — the behaviour described
as the target (continuous recognition, interim results while the person is still
speaking, a stable final afterwards), running entirely locally on system audio.

    cargo run --bin stt_spike --manifest-path apps/desktop/src-tauri/Cargo.toml \
      | packages/stt-bench/.venv/Scripts/python.exe \
        packages/stt-bench/scripts/live_spike.py nemo-80ms

Audio arrives on stdin as raw 16 kHz mono PCM16 from the Rust capture binary,
which drives the same WASAPI path the application uses. Interim text is
rewritten in place on one line; finals are committed to their own line, so the
output reads the way the overlay should behave.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from run_bench import ENGINES  # noqa: E402

#: Bytes per read. 1600 samples = 100 ms, matching the benchmark's feed size.
READ_SAMPLES = 1600
GREY = "\x1b[90m"
BOLD = "\x1b[1m"
RESET = "\x1b[0m"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("engine", nargs="?", default="nemo-80ms", choices=sorted(ENGINES))
    parser.add_argument("--plain", action="store_true", help="disable ANSI rewriting")
    args = parser.parse_args()

    engine = ENGINES[args.engine]()
    print(f"loading {args.engine}...", file=sys.stderr)
    load_started = time.monotonic()
    engine.start()
    print(
        f"ready in {time.monotonic() - load_started:.1f}s — play audio through your "
        f"speakers (a meeting, a video, anything)",
        file=sys.stderr,
    )
    print("-" * 70, file=sys.stderr)

    stdin = sys.stdin.buffer
    started = time.monotonic()
    line_len = 0
    first_partial_at: float | None = None
    utterance_started: float | None = None

    def clear_line() -> None:
        nonlocal line_len
        if line_len and not args.plain:
            sys.stdout.write("\r" + " " * line_len + "\r")
        line_len = 0

    try:
        while True:
            raw = stdin.read(READ_SAMPLES * 2)
            if not raw:
                break
            samples = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
            engine.feed_audio(samples)

            for event in engine.poll():
                now = time.monotonic() - started
                if event.is_final:
                    clear_line()
                    latency = ""
                    if first_partial_at is not None and utterance_started is not None:
                        latency = (
                            f"  {GREY}[first text +{(first_partial_at - utterance_started) * 1000:.0f}ms]{RESET}"
                            if not args.plain
                            else ""
                        )
                    print(f"{BOLD}FINAL{RESET}  {event.text}{latency}"
                          if not args.plain else f"FINAL  {event.text}")
                    sys.stdout.flush()
                    first_partial_at = None
                    utterance_started = None
                else:
                    if first_partial_at is None:
                        first_partial_at = time.monotonic()
                        utterance_started = time.monotonic() - 0.0
                    text = f"…{event.text}"
                    if args.plain:
                        print(text)
                    else:
                        clear_line()
                        sys.stdout.write(f"{GREY}{text}{RESET}")
                        line_len = len(text)
                    sys.stdout.flush()
    except KeyboardInterrupt:
        pass

    clear_line()
    for event in engine.stop():
        if event.is_final:
            print(f"FINAL  {event.text}")
    print(f"\nfull transcript:\n{engine.get_final()}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
