"""Коллектор операционных метрик: requests, latency, errors.

Лёгкая замена Prometheus для внутреннего использования — выдаёт текстовое
представление, пригодное для форматирования в Markdown админом.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from contextlib import contextmanager
from dataclasses import dataclass, field
from statistics import mean, median


@dataclass(slots=True)
class Counter:
    name: str
    value: int = 0

    def inc(self, amount: int = 1) -> None:
        self.value += amount

    def reset(self) -> None:
        self.value = 0


@dataclass(slots=True)
class Histogram:
    name: str
    samples: list[float] = field(default_factory=list)
    max_samples: int = 1000

    def observe(self, value: float) -> None:
        self.samples.append(value)
        if len(self.samples) > self.max_samples:
            self.samples = self.samples[-self.max_samples:]

    def percentile(self, p: float) -> float:
        if not self.samples:
            return 0.0
        sorted_s = sorted(self.samples)
        k = int((len(sorted_s) - 1) * p / 100.0)
        return sorted_s[k]

    @property
    def count(self) -> int:
        return len(self.samples)

    @property
    def avg(self) -> float:
        return mean(self.samples) if self.samples else 0.0

    @property
    def p50(self) -> float:
        return median(self.samples) if self.samples else 0.0

    @property
    def p95(self) -> float:
        return self.percentile(95.0)

    @property
    def p99(self) -> float:
        return self.percentile(99.0)


@dataclass(slots=True)
class Gauge:
    name: str
    value: float = 0.0

    def set(self, v: float) -> None:
        self.value = v

    def inc(self, v: float = 1.0) -> None:
        self.value += v

    def dec(self, v: float = 1.0) -> None:
        self.value -= v


class MetricsCollector:
    def __init__(self) -> None:
        self._counters: dict[str, Counter] = {}
        self._histograms: dict[str, Histogram] = {}
        self._gauges: dict[str, Gauge] = {}
        self._labels: dict[str, str] = {}

    def counter(self, name: str) -> Counter:
        c = self._counters.get(name)
        if c is None:
            c = Counter(name=name)
            self._counters[name] = c
        return c

    def histogram(self, name: str) -> Histogram:
        h = self._histograms.get(name)
        if h is None:
            h = Histogram(name=name)
            self._histograms[name] = h
        return h

    def gauge(self, name: str) -> Gauge:
        g = self._gauges.get(name)
        if g is None:
            g = Gauge(name=name)
            self._gauges[name] = g
        return g

    def set_label(self, key: str, value: str) -> None:
        self._labels[key] = value

    @contextmanager
    def timer(self, name: str):
        start = time.monotonic()
        try:
            yield
        finally:
            elapsed_ms = (time.monotonic() - start) * 1000.0
            self.histogram(name).observe(elapsed_ms)

    def measure(self, name: str) -> Callable:
        """Декоратор для синхронной функции."""

        def wrapper(func):
            def inner(*args, **kwargs):
                with self.timer(name):
                    return func(*args, **kwargs)
            return inner
        return wrapper

    def snapshot(self) -> dict:
        """Возвращает текущий снимок всех метрик."""
        return {
            "counters": {k: v.value for k, v in self._counters.items()},
            "gauges": {k: v.value for k, v in self._gauges.items()},
            "histograms": {
                k: {
                    "count": h.count,
                    "avg": h.avg,
                    "p50": h.p50,
                    "p95": h.p95,
                    "p99": h.p99,
                }
                for k, h in self._histograms.items()
            },
            "labels": dict(self._labels),
        }

    def reset(self) -> None:
        for c in self._counters.values():
            c.reset()
        for h in self._histograms.values():
            h.samples.clear()


__all__ = ["Counter", "Gauge", "Histogram", "MetricsCollector"]
