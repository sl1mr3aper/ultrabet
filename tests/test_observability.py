"""Тесты services/observability — Sentry + Prometheus, "мягкая" инициализация."""

from __future__ import annotations

import socket
from dataclasses import dataclass
from typing import Any

import pytest

from services import observability


@dataclass
class _Settings:
    sentry_dsn_value: str | None = None
    sentry_environment: str = "test"
    sentry_traces_sample_rate: float = 0.0
    prometheus_port: int = 0


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture(autouse=True)
def _reset() -> None:
    observability._reset_for_tests()


def test_metrics_default_is_noop() -> None:
    metrics = observability.get_metrics()
    assert metrics.enabled is False
    # Любой вызов метрик не должен бросать.
    metrics.bot_started.inc()
    metrics.handler_calls.labels(handler="x").inc()
    metrics.sstats_latency.labels(endpoint="y").observe(0.1)


def test_init_sentry_without_dsn_returns_false() -> None:
    settings = _Settings(sentry_dsn_value=None)
    assert observability.init_sentry(settings) is False


def test_init_sentry_with_dsn_imports_or_warns(monkeypatch: pytest.MonkeyPatch) -> None:
    # Симулируем ситуацию "DSN задан". Если sentry_sdk установлен — успешный
    # init; если нет — модуль возвращает False.
    settings = _Settings(sentry_dsn_value="https://public@sentry.example/1")
    sentry_present: bool = True
    try:
        import sentry_sdk  # type: ignore[import-not-found]
    except ImportError:  # pragma: no cover
        sentry_present = False
    inited: list[bool] = []

    def fake_init(**kwargs: Any) -> None:
        inited.append(True)

    if sentry_present:
        import sentry_sdk  # type: ignore[import-not-found]
        monkeypatch.setattr(sentry_sdk, "init", fake_init)
        assert observability.init_sentry(settings) is True
        assert inited == [True]
        # повторный вызов не должен инициализировать второй раз.
        assert observability.init_sentry(settings) is True
        assert inited == [True]
    else:  # pragma: no cover
        assert observability.init_sentry(settings) is False


def test_prometheus_disabled_when_port_zero() -> None:
    settings = _Settings(prometheus_port=0)
    assert observability.start_prometheus_server(settings) is False
    metrics = observability.get_metrics()
    assert metrics.enabled is False


def test_prometheus_starts_on_real_port() -> None:
    pytest.importorskip("prometheus_client")
    port = _free_port()
    settings = _Settings(prometheus_port=port)
    assert observability.start_prometheus_server(settings) is True
    metrics = observability.get_metrics()
    assert metrics.enabled is True
    metrics.bot_started.inc()
    metrics.handler_calls.labels(handler="t").inc()
    # Проверяем, что сервер слушает порт.
    s = socket.socket()
    try:
        s.settimeout(1.0)
        s.connect(("127.0.0.1", port))
    finally:
        s.close()
