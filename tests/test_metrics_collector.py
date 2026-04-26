"""Тесты MetricsCollector."""

from __future__ import annotations

import time

from services.metrics_collector import MetricsCollector


def test_counter():
    m = MetricsCollector()
    c = m.counter("requests")
    c.inc()
    c.inc(5)
    assert c.value == 6


def test_counter_reused():
    m = MetricsCollector()
    m.counter("x").inc()
    m.counter("x").inc()
    assert m.counter("x").value == 2


def test_gauge():
    m = MetricsCollector()
    g = m.gauge("active")
    g.set(10)
    g.inc()
    g.dec(3)
    assert g.value == 8


def test_histogram_stats():
    m = MetricsCollector()
    h = m.histogram("latency")
    for i in range(1, 101):
        h.observe(float(i))
    assert h.count == 100
    assert h.avg == 50.5
    assert h.p50 == 50.5
    assert h.p95 == 95
    assert h.p99 == 99


def test_histogram_caps_samples():
    m = MetricsCollector()
    h = m.histogram("x")
    h.max_samples = 5
    for i in range(10):
        h.observe(i)
    assert h.count == 5
    assert h.samples[0] == 5


def test_timer_context():
    m = MetricsCollector()
    with m.timer("sleep"):
        time.sleep(0.01)
    h = m.histogram("sleep")
    assert h.count == 1
    assert h.samples[0] >= 5  # at least 5ms


def test_measure_decorator():
    m = MetricsCollector()

    @m.measure("compute")
    def square(x):
        return x * x

    assert square(3) == 9
    assert m.histogram("compute").count == 1


def test_snapshot():
    m = MetricsCollector()
    m.counter("hits").inc(3)
    m.gauge("queue").set(5)
    m.histogram("ms").observe(100.0)
    snap = m.snapshot()
    assert snap["counters"]["hits"] == 3
    assert snap["gauges"]["queue"] == 5
    assert snap["histograms"]["ms"]["count"] == 1


def test_reset():
    m = MetricsCollector()
    m.counter("x").inc(10)
    m.histogram("h").observe(5)
    m.reset()
    assert m.counter("x").value == 0
    assert m.histogram("h").count == 0


def test_labels():
    m = MetricsCollector()
    m.set_label("env", "prod")
    snap = m.snapshot()
    assert snap["labels"]["env"] == "prod"
