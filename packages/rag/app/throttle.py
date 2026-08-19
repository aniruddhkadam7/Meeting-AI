"""STT/RAG scheduling coordination (Phase B of the STT low-end optimization
pass — see docs/stt-performance-phase2.md).

Goal: when STT is actively running on low-end hardware, RAG document
indexing (the CPU-heavy embedding step specifically) should get out of the
way rather than compete for CPU. Retrieval (`/search`) is explicitly never
throttled — a user waiting on an answer must never be slowed down by this
mechanism.

Signaled by Rust (`apps/desktop/src-tauri/src/rag/client.rs`'s
`set_throttle`) via a new internal HTTP endpoint (`POST /internal/throttle`,
see routes.py) rather than a file or a new IPC channel — RAG already runs an
HTTP server and Rust already talks to it, so this reuses the existing
transport with the smallest possible surface.

Never blocks/rejects a request: an upload that arrives while STT is active
is not dropped or failed — `wait_while_throttled()` sleeps in short
increments until the throttle clears (or its own safety TTL expires), then
proceeds normally. This satisfies "do not lose queued indexing work" without
needing an actual queue — the one already-synchronous request handler is
the queue, in the sense that FastAPI/uvicorn already serializes requests to
this single worker.

Safety against "STT ends abnormally and never explicitly un-throttles"
(e.g. the desktop app crashes mid-recording): every `set_active(True)` call
carries a short TTL. If Rust does not refresh it (which it does on a timer
while STT is running — see rag/process.rs's throttle-refresh loop) within
that window, the throttle auto-expires and indexing resumes on its own,
never permanently starved by a crash.
"""

from __future__ import annotations

import logging
import threading
import time

logger = logging.getLogger("rag.throttle")

# How long a single "STT is active" signal remains valid without being
# refreshed. Rust refreshes on a shorter interval than this while STT is
# running (see rag/process.rs) — this is the dead-man's-switch window, not
# the normal refresh cadence, so it can be generous without meaningfully
# delaying recovery from a crash.
_TTL_S = 10.0

# How long wait_while_throttled() sleeps between re-checks. Short enough
# that indexing resumes promptly once STT ends; long enough not to spin.
_POLL_INTERVAL_S = 0.5

# Hard ceiling on total time an embed() call will wait before proceeding
# anyway — a very long STT session (a full interview) must not indefinitely
# starve indexing altogether; it should just yield priority while it can.
_MAX_WAIT_S = 30.0


class _ThrottleState:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._active_until: float | None = None

    def set_active(self, active: bool) -> None:
        with self._lock:
            if active:
                self._active_until = time.monotonic() + _TTL_S
            else:
                self._active_until = None

    def is_active(self) -> bool:
        with self._lock:
            if self._active_until is None:
                return False
            if time.monotonic() >= self._active_until:
                # TTL expired without a refresh — treat as no longer active
                # (the dead-man's-switch: see module doc).
                self._active_until = None
                return False
            return True


_state = _ThrottleState()


def set_active(active: bool) -> None:
    """Called by the `/internal/throttle` route. `active=True` means "STT is
    running on low-end hardware, please yield" and must be refreshed within
    `_TTL_S` seconds or it auto-clears."""
    _state.set_active(active)


def is_active() -> bool:
    return _state.is_active()


def wait_while_throttled() -> float:
    """Blocks the calling thread while the throttle is active, polling at
    `_POLL_INTERVAL_S`, up to `_MAX_WAIT_S` total. Returns the number of
    seconds actually waited (0.0 if the throttle was never active) — purely
    for logging/observability, callers don't need to act on it.

    Called from the request-handling thread inside `embed()`, immediately
    before the CPU-heavy `model.encode()` call — never around file I/O,
    text extraction, or chunking, which are cheap and not what STT is
    contending with for CPU.
    """
    if not _state.is_active():
        return 0.0

    waited = 0.0
    while _state.is_active() and waited < _MAX_WAIT_S:
        time.sleep(_POLL_INTERVAL_S)
        waited += _POLL_INTERVAL_S

    if waited > 0:
        logger.info("[THROTTLE] embedding yielded to active STT for %.1fs", waited)
    return waited
