"""Security regression tests for production-only configuration
(app/core/config.py's `is_production`, app/main.py's docs_url wiring)."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.config import Settings


def _build_app(settings: Settings) -> FastAPI:
    """Mirrors app/main.py's FastAPI construction exactly, without the
    module-level import-time side effects that make reloading the real
    `app.main` module for a single test unreliable."""
    return FastAPI(
        title="Smallbird Backend",
        version="0.1.0",
        docs_url=None if settings.is_production else "/docs",
        redoc_url=None if settings.is_production else "/redoc",
        openapi_url=None if settings.is_production else "/openapi.json",
    )


def test_is_production_true_only_for_production_value():
    assert Settings.is_production.fget(_settings_with_env("production")) is True
    assert Settings.is_production.fget(_settings_with_env("PRODUCTION")) is True
    assert Settings.is_production.fget(_settings_with_env("development")) is False
    assert Settings.is_production.fget(_settings_with_env("")) is False


def _settings_with_env(value: str) -> Settings:
    settings = Settings()
    settings.environment = value
    return settings


def test_docs_enabled_when_not_production():
    settings = Settings()
    settings.environment = "development"
    client = TestClient(_build_app(settings))
    assert client.get("/docs").status_code == 200
    assert client.get("/redoc").status_code == 200
    assert client.get("/openapi.json").status_code == 200


def test_docs_disabled_in_production():
    settings = Settings()
    settings.environment = "production"
    client = TestClient(_build_app(settings))
    assert client.get("/docs").status_code == 404
    assert client.get("/redoc").status_code == 404
    assert client.get("/openapi.json").status_code == 404
