"""Tests for STT/RAG scheduling coordination (Phase B — see
docs/stt-performance-phase2.md and app/throttle.py's module doc).

Uses a short monkeypatched TTL/poll-interval so these tests run in
milliseconds rather than actually waiting out the production 10s TTL /
0.5s poll interval.
"""

from __future__ import annotations

import threading
import time

import app.throttle as throttle_module
from app.throttle import _ThrottleState


def test_inactive_by_default():
    state = _ThrottleState()
    assert state.is_active() is False


def test_set_active_true_makes_it_active():
    state = _ThrottleState()
    state.set_active(True)
    assert state.is_active() is True


def test_set_active_false_clears_it():
    state = _ThrottleState()
    state.set_active(True)
    state.set_active(False)
    assert state.is_active() is False


def test_ttl_expiry_auto_clears_without_explicit_deactivation(monkeypatch):
    """The dead-man's-switch: simulates 'STT ended abnormally and never
    called set_active(False)' — the throttle must clear itself once the TTL
    elapses, not stay active forever."""
    monkeypatch.setattr(throttle_module, "_TTL_S", 0.05)
    state = _ThrottleState()
    state.set_active(True)
    assert state.is_active() is True
    time.sleep(0.08)
    assert state.is_active() is False, "throttle must auto-expire after TTL without a refresh"


def test_refreshing_before_ttl_expires_keeps_it_active(monkeypatch):
    """Mirrors Rust's periodic refresh loop while STT is genuinely still
    running — repeated set_active(True) calls before the TTL lapses must
    keep the throttle active continuously."""
    monkeypatch.setattr(throttle_module, "_TTL_S", 0.1)
    state = _ThrottleState()
    state.set_active(True)
    for _ in range(5):
        time.sleep(0.04)  # well under the 0.1s TTL
        state.set_active(True)  # refresh
        assert state.is_active() is True
    # After the loop, even a bit past the last refresh but still within TTL:
    time.sleep(0.05)
    assert state.is_active() is True


def test_wait_while_throttled_returns_immediately_when_inactive():
    throttle_module._state = _ThrottleState()
    waited = throttle_module.wait_while_throttled()
    assert waited == 0.0


def test_wait_while_throttled_blocks_until_deactivated(monkeypatch):
    monkeypatch.setattr(throttle_module, "_POLL_INTERVAL_S", 0.02)
    monkeypatch.setattr(throttle_module, "_MAX_WAIT_S", 5.0)
    throttle_module._state = _ThrottleState()
    throttle_module.set_active(True)

    results = []

    def waiter():
        results.append(throttle_module.wait_while_throttled())

    t = threading.Thread(target=waiter)
    t.start()
    time.sleep(0.1)  # let it block for a bit
    throttle_module.set_active(False)
    t.join(timeout=2.0)

    assert not t.is_alive(), "wait_while_throttled must return once deactivated"
    assert results[0] > 0.0, "should report a nonzero wait when it genuinely blocked"


def test_wait_while_throttled_respects_max_wait_ceiling(monkeypatch):
    """Even if the throttle is never explicitly cleared and its TTL is long,
    a single embed() call must not wait forever — MAX_WAIT_S bounds it so a
    long STT session doesn't starve indexing indefinitely."""
    monkeypatch.setattr(throttle_module, "_POLL_INTERVAL_S", 0.02)
    monkeypatch.setattr(throttle_module, "_MAX_WAIT_S", 0.1)
    monkeypatch.setattr(throttle_module, "_TTL_S", 10.0)  # long TTL, never expires on its own
    throttle_module._state = _ThrottleState()
    throttle_module.set_active(True)

    started = time.monotonic()
    waited = throttle_module.wait_while_throttled()
    elapsed = time.monotonic() - started

    assert elapsed < 1.0, "must not wait indefinitely even if never explicitly deactivated"
    assert waited > 0.0


def test_repeated_activate_deactivate_cycles_behave_correctly(monkeypatch):
    """Mirrors 'repeated STT sessions' from the brief's test list — the
    throttle must correctly activate and clear across multiple independent
    sessions, not leak state between them."""
    monkeypatch.setattr(throttle_module, "_TTL_S", 1.0)
    state = _ThrottleState()
    for _ in range(3):
        assert state.is_active() is False
        state.set_active(True)
        assert state.is_active() is True
        state.set_active(False)
        assert state.is_active() is False
