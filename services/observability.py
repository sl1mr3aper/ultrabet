"""P0-2: интеграция Sentry + Prometheus.

Модуль умышленно «мягкий»:
- если ``sentry-sdk`` или ``prometheus_client`` не установлены, или
  соответствующие переменные конфига не заданы, инициализация просто
  логирует и возвращается без ошибки.
- инициализация идемпотентна: повторный вызов не плодит обработчики.

Использование (в main.py):

    from services.observability import (
        init_sentry, start_prometheus_server, get_metrics
    )

    init_sentry(settings)
    start_prometheus_server(settings)
    metrics = get_metrics()
    metrics.bot_started.inc()
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Any

from loguru import logger


@dataclass
class _MetricsRegistry:
    """Лёгкая обёртка над набором счётчиков/гистограмм Prometheus.

    Если ``prometheus_client`` не установлен, все методы — no-op (incr/observe
    просто игнорируются). Это позволяет вставлять `metrics.foo.inc()` в
    коде без условных проверок.
    """

    enabled: bool = False
    bot_started: Any = None
    handler_calls: Any = None
    handler_errors: Any = None
    sstats_requests: Any = None
    sstats_errors: Any = None
    sstats_latency: Any = None
    self_learn_runs: Any = None
    secondary_calibrator_runs: Any = None
    cache_hits: Any = None
    cache_misses: Any = None
    db_pool_size: Any = None


class _NoopMetric:
    """Фолбэк для случая «prometheus_client не установлен»."""

    def __init__(self, *_a: object, **_kw: object) -> None: ...

    def labels(self, *_a: object, **_kw: object) -> _NoopMetric:
        return self

    def inc(self, *_a: object, **_kw: object) -> None: ...

    def observe(self, *_a: object, **_kw: object) -> None: ...

    def set(self, *_a: object, **_kw: object) -> None: ...


_METRICS: _MetricsRegistry | None = None
_PROM_SERVER_STARTED = False
_SENTRY_INITED = False
_LOCK = threading.Lock()


def _build_metrics(enabled: bool) -> _MetricsRegistry:
    if not enabled:
        noop = _NoopMetric()
        return _MetricsRegistry(
            enabled=False,
            bot_started=noop,
            handler_calls=noop,
            handler_errors=noop,
            sstats_requests=noop,
            sstats_errors=noop,
            sstats_latency=noop,
            self_learn_runs=noop,
            secondary_calibrator_runs=noop,
            cache_hits=noop,
            cache_misses=noop,
            db_pool_size=noop,
        )

    from prometheus_client import Counter, Gauge, Histogram

    return _MetricsRegistry(
        enabled=True,
        bot_started=Counter(
            "ultrabet_bot_started_total",
            "Бот успешно стартовал",
        ),
        handler_calls=Counter(
            "ultrabet_handler_calls_total",
            "Количество вызовов handler'а",
            ["handler"],
        ),
        handler_errors=Counter(
            "ultrabet_handler_errors_total",
            "Количество исключений в handler'ах",
            ["handler"],
        ),
        sstats_requests=Counter(
            "ultrabet_sstats_requests_total",
            "Запросы к SStats API",
            ["endpoint"],
        ),
        sstats_errors=Counter(
            "ultrabet_sstats_errors_total",
            "Ошибки SStats API",
            ["endpoint", "kind"],
        ),
        sstats_latency=Histogram(
            "ultrabet_sstats_latency_seconds",
            "Латентность SStats API",
            ["endpoint"],
            buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0),
        ),
        self_learn_runs=Counter(
            "ultrabet_self_learner_runs_total",
            "Количество прогонов SelfLearner",
            ["status"],
        ),
        secondary_calibrator_runs=Counter(
            "ultrabet_secondary_calibrator_runs_total",
            "Количество прогонов SecondaryPickCalibrator",
            ["status"],
        ),
        cache_hits=Counter(
            "ultrabet_cache_hits_total",
            "Cache hits",
            ["cache"],
        ),
        cache_misses=Counter(
            "ultrabet_cache_misses_total",
            "Cache misses",
            ["cache"],
        ),
        db_pool_size=Gauge(
            "ultrabet_db_pool_size",
            "Размер пула соединений к БД",
        ),
    )


def get_metrics() -> _MetricsRegistry:
    """Возвращает реестр метрик (создаёт no-op, если ещё не было init)."""
    global _METRICS
    if _METRICS is None:
        _METRICS = _build_metrics(enabled=False)
    return _METRICS


def init_sentry(settings: Any) -> bool:
    """Инициализирует Sentry, если задан ``settings.sentry_dsn`` и установлен SDK.

    Возвращает True, если Sentry активен.
    """
    global _SENTRY_INITED
    with _LOCK:
        if _SENTRY_INITED:
            return True

        dsn = getattr(settings, "sentry_dsn_value", None)
        if not dsn:
            return False
        try:
            import sentry_sdk  # type: ignore[import-not-found]
        except ImportError:
            logger.warning(
                "sentry_sdk не установлен; добавь sentry-sdk в requirements"
            )
            return False

        traces = float(getattr(settings, "sentry_traces_sample_rate", 0.0) or 0.0)
        env = str(getattr(settings, "sentry_environment", "production"))

        sentry_sdk.init(
            dsn=dsn,
            environment=env,
            traces_sample_rate=traces,
            send_default_pii=False,
            attach_stacktrace=True,
        )
        _SENTRY_INITED = True
        logger.info(
            "Sentry initialised (env={}, traces={})", env, traces
        )
        return True


def start_prometheus_server(settings: Any) -> bool:
    """Поднимает HTTP-сервер ``prometheus_client`` на ``settings.prometheus_port``.

    Также создаёт реестр метрик. Возвращает True, если сервер поднят.
    """
    global _METRICS, _PROM_SERVER_STARTED
    with _LOCK:
        port = int(getattr(settings, "prometheus_port", 0) or 0)
        if port <= 0:
            # Метрики всё равно нужны — но в no-op режиме.
            if _METRICS is None:
                _METRICS = _build_metrics(enabled=False)
            return False

        if _PROM_SERVER_STARTED:
            return True

        try:
            from prometheus_client import start_http_server
        except ImportError:
            logger.warning(
                "prometheus_client не установлен; "
                "PROMETHEUS_PORT задан, но метрики недоступны"
            )
            if _METRICS is None:
                _METRICS = _build_metrics(enabled=False)
            return False

        _METRICS = _build_metrics(enabled=True)
        start_http_server(port)
        _PROM_SERVER_STARTED = True
        logger.info("Prometheus metrics on :{}/metrics", port)
        return True


def _reset_for_tests() -> None:
    """Только для юнит-тестов: сбросить кэш модуля."""
    global _METRICS, _PROM_SERVER_STARTED, _SENTRY_INITED
    with _LOCK:
        _METRICS = None
        _PROM_SERVER_STARTED = False
        _SENTRY_INITED = False


__all__ = [
    "get_metrics",
    "init_sentry",
    "start_prometheus_server",
]
