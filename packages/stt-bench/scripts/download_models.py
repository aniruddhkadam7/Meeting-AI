"""One-time model installer for the STT benchmark.

    py -3 packages/stt-bench/scripts/download_models.py            # all candidates
    py -3 packages/stt-bench/scripts/download_models.py zipformer-en-kroko ...

Re-running is safe and cheap: already-installed models are skipped without any
network access, which is the same behaviour the shipping app needs (download
once at setup, never on start-up).
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sttbench import models  # noqa: E402


def main(argv: list[str]) -> int:
    keys = argv or list(models.REGISTRY)
    unknown = [k for k in keys if k not in models.REGISTRY]
    if unknown:
        print(f"unknown model(s): {', '.join(unknown)}")
        print(f"available: {', '.join(models.REGISTRY)}")
        return 2

    root = models.model_root()
    print(f"Model directory: {root}")
    root.mkdir(parents=True, exist_ok=True)

    failures: list[tuple[str, str]] = []
    for key in keys:
        if models.is_installed(key):
            size = models.dir_size_bytes(models.model_path(key))
            print(f"  {key}: already installed ({size / 1e6:.0f} MB)")
            continue
        try:
            models.ensure_model(key)
            size = models.dir_size_bytes(models.model_path(key))
            print(f"  {key}: installed ({size / 1e6:.0f} MB)")
        except Exception as exc:  # noqa: BLE001
            print(f"  {key}: FAILED — {exc}")
            failures.append((key, str(exc)))

    print()
    total = sum(models.dir_size_bytes(models.model_path(k)) for k in models.REGISTRY)
    print(f"Total installed: {total / 1e6:.0f} MB")
    if failures:
        print(f"{len(failures)} model(s) failed; the benchmark will skip them and say so.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
