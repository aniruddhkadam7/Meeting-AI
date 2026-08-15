"""Standalone STT benchmark harness.

This package is a *spike*: it exists to measure candidate speech-to-text engines
against each other on identical audio, and is deliberately isolated from the
desktop application. Nothing in `apps/desktop` imports it, and it imports
nothing from the production pipeline.

See `packages/stt-bench/README.md` for how to run it.
"""

__all__ = ["sentences", "audio", "engines", "metrics", "runner"]
