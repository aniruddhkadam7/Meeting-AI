"""Records the four benchmark sentences from your microphone, once.

Run this once. The resulting WAVs become the fixed corpus that every candidate
STT engine is scored against, so the accuracy comparison is apples-to-apples.

    py -3 packages/stt-bench/scripts/record_corpus.py

For each sentence: press ENTER to start recording, read the sentence aloud at
normal interview speed, then press ENTER again to stop. You are shown the peak
level and can re-record any take you are not happy with.

Audio is written to packages/stt-bench/corpus/human/ and never leaves this
machine.
"""

from __future__ import annotations

import sys
import threading
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sttbench.audio import SAMPLE_RATE, Clip, peak_dbfs, rms, write_wav  # noqa: E402
from sttbench.sentences import SENTENCES  # noqa: E402

CORPUS_DIR = Path(__file__).resolve().parent.parent / "corpus" / "human"

# Below this the take is too quiet for a fair test — every engine degrades on
# low-level audio and we would be measuring gain, not the engine.
MIN_PEAK_DBFS = -30.0
# Above this the take is clipping, which also penalizes engines unfairly.
MAX_PEAK_DBFS = -0.5


def record_until_enter() -> np.ndarray:
    """Captures mono 16 kHz audio until the user presses ENTER."""
    import sounddevice as sd

    frames: list[np.ndarray] = []
    done = threading.Event()

    def callback(indata, _frames, _time, status):
        if status:
            print(f"  [audio status] {status}", file=sys.stderr)
        frames.append(indata[:, 0].copy())

    with sd.InputStream(
        samplerate=SAMPLE_RATE,
        channels=1,
        dtype="float32",
        callback=callback,
        blocksize=int(SAMPLE_RATE * 0.02),  # 20 ms, same as the app's WASAPI buffer
    ):
        waiter = threading.Thread(target=lambda: (input(), done.set()), daemon=True)
        waiter.start()
        while not done.is_set():
            done.wait(0.05)

    if not frames:
        return np.zeros(0, dtype=np.float32)
    return np.concatenate(frames)


def describe(samples: np.ndarray) -> str:
    return (
        f"{len(samples) / SAMPLE_RATE:5.2f}s  "
        f"peak {peak_dbfs(samples):6.1f} dBFS  "
        f"rms {rms(samples):.4f}"
    )


def verdict(samples: np.ndarray) -> str | None:
    if len(samples) < SAMPLE_RATE * 0.5:
        return "too short — did the recording start before you spoke?"
    peak = peak_dbfs(samples)
    if peak < MIN_PEAK_DBFS:
        return "too quiet — move closer to the mic or raise the input gain"
    if peak > MAX_PEAK_DBFS:
        return "clipping — lower the input gain"
    return None


def main() -> int:
    try:
        import sounddevice as sd
    except ImportError:
        print("sounddevice is not installed. Run: py -3 -m pip install sounddevice")
        return 1

    try:
        device = sd.query_devices(kind="input")
    except Exception as exc:  # noqa: BLE001
        print(f"No usable input device found: {exc}")
        return 1

    print("=" * 68)
    print("STT BENCHMARK CORPUS RECORDER")
    print("=" * 68)
    print(f"Input device : {device['name']}")
    print(f"Format       : {SAMPLE_RATE} Hz mono (matches the app's STT pipeline)")
    print(f"Output        : {CORPUS_DIR}")
    print()
    print("Read each sentence aloud at normal interview speed — the pace an")
    print("interviewer would actually use. Don't over-enunciate; we want to")
    print("measure the engines on realistic speech.")
    print()

    for index, sentence in enumerate(SENTENCES, start=1):
        target = CORPUS_DIR / f"{sentence.id}.wav"
        while True:
            print("-" * 68)
            print(f"[{index}/{len(SENTENCES)}] Read this aloud:\n")
            print(f'    "{sentence.text}"\n')
            input("Press ENTER to START recording... ")
            print("  ● recording — press ENTER when you have finished the sentence")
            samples = record_until_enter()
            print(f"  stopped: {describe(samples)}")

            problem = verdict(samples)
            if problem:
                print(f"  ✗ {problem}")
                print("  Let's try that one again.\n")
                continue

            choice = input("  Keep this take? [Y/n/r=replay] ").strip().lower()
            if choice == "r":
                sd.play(samples, SAMPLE_RATE)
                sd.wait()
                choice = input("  Keep this take? [Y/n] ").strip().lower()
            if choice in ("", "y", "yes"):
                write_wav(target, Clip(samples))
                print(f"  ✓ saved {target.name}\n")
                break
            print("  Re-recording.\n")

    print("=" * 68)
    print("Done. Recorded corpus:")
    for sentence in SENTENCES:
        path = CORPUS_DIR / f"{sentence.id}.wav"
        size_kb = path.stat().st_size / 1024 if path.exists() else 0
        print(f"  {path.name}  {size_kb:7.1f} KB")
    print()
    print("Next: the benchmark runner will replay these through every engine.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
