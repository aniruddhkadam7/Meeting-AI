"""Regression tests for the hardware-tier-driven embedding config
(RAG_EMBED_BATCH_SIZE / RAG_TORCH_THREADS, see
apps/desktop/src-tauri/src/hardware/manager.rs and
docs/performance-tuning.md's RAG sweep). These verify the wiring from
Settings -> LocalEmbeddingProvider -> torch/sentence-transformers actually
happens, not just that the Rust-side tier table has the right numbers —
the Rust regression tests (hardware::manager::tests) cover tier selection;
these cover that a selected config genuinely reaches the embedding model.

Uses a fake torch/sentence_transformers module (not the real ~90MB model)
so this suite stays fast, matching the FakeEmbeddingProvider pattern already
used in conftest.py/test_pipeline.py for the same reason.
"""

from __future__ import annotations

import sys
import types
from unittest.mock import MagicMock

import pytest

from app.core.config import Settings
from app.embeddings import LocalEmbeddingProvider, get_embedding_provider
import app.embeddings as embeddings_module


@pytest.fixture(autouse=True)
def _reset_global_provider_singleton():
    """get_embedding_provider() caches a module-global singleton — reset it
    around every test in this file so one test's provider construction
    doesn't leak into the next test's assertions."""
    embeddings_module._provider = None
    yield
    embeddings_module._provider = None


@pytest.fixture
def fake_torch_and_sentence_transformers(monkeypatch):
    """Replaces `torch` and `sentence_transformers` with mocks before
    LocalEmbeddingProvider imports them (the real import happens lazily
    inside `_ensure_loaded`, so patching sys.modules here is enough — no
    need to patch anything at import time of this test file)."""
    fake_torch = types.ModuleType("torch")
    fake_torch.set_num_threads = MagicMock()
    monkeypatch.setitem(sys.modules, "torch", fake_torch)

    fake_model = MagicMock()
    fake_model.encode.return_value = []

    fake_st_module = types.ModuleType("sentence_transformers")
    fake_st_module.SentenceTransformer = MagicMock(return_value=fake_model)
    monkeypatch.setitem(sys.modules, "sentence_transformers", fake_st_module)

    return fake_torch, fake_st_module.SentenceTransformer, fake_model


def test_local_embedding_provider_defaults_match_performance_tier_config_defaults():
    """LocalEmbeddingProvider's constructor defaults (torch_threads=4,
    batch_size=32) must match Settings' defaults (packages/rag/app/core/
    config.py) and the PERFORMANCE tier row in
    hardware/manager.rs::config_for_tier — today's shipped, unmodified
    behavior when no tier config is threaded through at all."""
    provider = LocalEmbeddingProvider("sentence-transformers/all-MiniLM-L6-v2", 384)
    assert provider._torch_threads == 4  # noqa: SLF001 — verifying internal wiring, not public API
    assert provider._batch_size == 32  # noqa: SLF001


@pytest.mark.parametrize(
    "torch_threads,batch_size",
    [
        (1, 8),    # ENTRY tier
        (2, 16),   # STANDARD tier
        (4, 32),   # PERFORMANCE tier
        (8, 32),   # HIGH_PERFORMANCE tier (torch_threads varies with cores; 8 is the clamp ceiling)
    ],
)
def test_ensure_loaded_applies_the_configured_thread_count_to_torch(
    fake_torch_and_sentence_transformers, torch_threads, batch_size
):
    """For every tier's (torch_threads, batch_size) pair, loading the model
    must call torch.set_num_threads with exactly that thread count —
    proving the config actually reaches torch, not just that the numbers
    are stored on the provider object."""
    fake_torch, _, _ = fake_torch_and_sentence_transformers
    provider = LocalEmbeddingProvider(
        "sentence-transformers/all-MiniLM-L6-v2", 384, torch_threads=torch_threads, batch_size=batch_size
    )
    provider._ensure_loaded()  # noqa: SLF001
    fake_torch.set_num_threads.assert_called_once_with(torch_threads)


def test_embed_passes_the_configured_batch_size_to_encode(fake_torch_and_sentence_transformers):
    """The batch_size passed to LocalEmbeddingProvider must reach
    SentenceTransformer.encode()'s batch_size kwarg — the RAG sweep found
    batch size affects memory, not latency, but it must still actually be
    applied, not silently dropped."""
    _, _, fake_model = fake_torch_and_sentence_transformers
    provider = LocalEmbeddingProvider(
        "sentence-transformers/all-MiniLM-L6-v2", 384, torch_threads=4, batch_size=16
    )
    provider.embed(["hello", "world"])
    _, kwargs = fake_model.encode.call_args
    assert kwargs["batch_size"] == 16


def test_embed_yields_to_active_stt_throttle_before_encoding(fake_torch_and_sentence_transformers, monkeypatch):
    """STT/RAG scheduling coordination (Phase B, see app/throttle.py) —
    LocalEmbeddingProvider.embed() must call wait_while_throttled()
    immediately before the CPU-heavy encode() call. Proven here by
    replacing wait_while_throttled with a spy and confirming it ran before
    encode() was called, using the fake torch/sentence-transformers so this
    stays fast (no real model load)."""
    _, _, fake_model = fake_torch_and_sentence_transformers
    call_order = []
    fake_model.encode.side_effect = lambda *a, **k: call_order.append("encode") or []

    import app.throttle as throttle_module

    def spy_wait():
        call_order.append("wait_while_throttled")
        return 0.0

    monkeypatch.setattr(throttle_module, "wait_while_throttled", spy_wait)

    provider = LocalEmbeddingProvider("sentence-transformers/all-MiniLM-L6-v2", 384)
    provider.embed(["hello"])

    assert call_order == ["wait_while_throttled", "encode"], (
        "embed() must check the throttle immediately before encode(), not after or not at all"
    )


def test_embed_of_empty_texts_does_not_touch_the_throttle(fake_torch_and_sentence_transformers, monkeypatch):
    """embed([]) short-circuits before loading the model at all — must not
    even check the throttle, since there is no CPU-heavy work to yield
    around."""
    import app.throttle as throttle_module

    called = []
    monkeypatch.setattr(throttle_module, "wait_while_throttled", lambda: called.append(True))

    provider = LocalEmbeddingProvider("sentence-transformers/all-MiniLM-L6-v2", 384)
    result = provider.embed([])

    assert result == []
    assert called == []


def test_ensure_loaded_only_sets_torch_threads_once_even_across_multiple_embed_calls(
    fake_torch_and_sentence_transformers,
):
    """The model (and its thread count) is loaded once and reused — a
    performance-mode change mid-process should NOT retroactively alter an
    already-loaded model's thread count (that requires the process restart
    wired in rag::RagServiceHandle::restart, not a live mutation here)."""
    fake_torch, _, _ = fake_torch_and_sentence_transformers
    provider = LocalEmbeddingProvider(
        "sentence-transformers/all-MiniLM-L6-v2", 384, torch_threads=6, batch_size=32
    )
    provider.embed(["first call"])
    provider.embed(["second call"])
    fake_torch.set_num_threads.assert_called_once_with(6)


@pytest.fixture
def reloaded_config_module(monkeypatch):
    """Settings' fields are evaluated at class-body time (module import),
    the same reason `packages/rag/app/core/config.py`'s own doc comment
    says a performance-mode change requires restarting the process — so
    observing a different env value requires reloading the module fresh
    under the patched env, not just re-instantiating the already-imported
    class. Reloads back to the ambient environment afterward so this test's
    env patch can't leak into a later test's import state."""
    import importlib
    from app.core import config as config_module

    yield config_module, importlib
    importlib.reload(config_module)


def test_settings_reads_rag_embed_batch_size_and_torch_threads_from_env(monkeypatch, reloaded_config_module):
    """Settings' class-body os.getenv reads must actually pick up
    RAG_EMBED_BATCH_SIZE/RAG_TORCH_THREADS when set — this is the env-var
    injection point rag::process::RagServiceHandle::spawn writes to at
    child-process spawn time."""
    config_module, importlib = reloaded_config_module
    monkeypatch.setenv("RAG_EMBED_BATCH_SIZE", "64")
    monkeypatch.setenv("RAG_TORCH_THREADS", "8")
    importlib.reload(config_module)

    settings = config_module.Settings()
    assert settings.embed_batch_size == 64
    assert settings.torch_threads == 8


def test_settings_defaults_when_env_vars_are_unset(monkeypatch, reloaded_config_module):
    config_module, importlib = reloaded_config_module
    monkeypatch.delenv("RAG_EMBED_BATCH_SIZE", raising=False)
    monkeypatch.delenv("RAG_TORCH_THREADS", raising=False)
    importlib.reload(config_module)

    settings = config_module.Settings()
    assert settings.embed_batch_size == 32
    assert settings.torch_threads == 4


def test_get_embedding_provider_threads_settings_values_through(monkeypatch, reloaded_config_module):
    """get_embedding_provider() (the module-global singleton constructor
    packages/rag/app/routes.py actually calls) must pass Settings'
    embed_batch_size/torch_threads into the LocalEmbeddingProvider it
    builds — this is the last hop between config and the running model."""
    config_module, importlib = reloaded_config_module
    monkeypatch.setenv("RAG_EMBED_BATCH_SIZE", "16")
    monkeypatch.setenv("RAG_TORCH_THREADS", "2")
    importlib.reload(config_module)

    settings = config_module.get_settings()
    assert settings.embed_batch_size == 16
    assert settings.torch_threads == 2

    built = LocalEmbeddingProvider(
        settings.embedding_model,
        settings.embedding_dim,
        torch_threads=settings.torch_threads,
        batch_size=settings.embed_batch_size,
    )
    assert built._torch_threads == 2  # noqa: SLF001
    assert built._batch_size == 16  # noqa: SLF001
