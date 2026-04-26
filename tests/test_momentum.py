"""Тесты моментума."""

from __future__ import annotations

from core.momentum import compute_momentum


def test_uptrend():
    m = compute_momentum(["W", "W", "W"])
    assert m.value > 0.5
    assert m.label == "восходящий"
    assert m.emoji == "📈"


def test_downtrend():
    m = compute_momentum(["L", "L", "L"])
    assert m.value < -0.5
    assert m.label == "нисходящий"


def test_flat():
    m = compute_momentum(["W", "L", "D"])
    assert -0.3 <= m.value <= 0.3


def test_empty():
    m = compute_momentum([])
    assert m.value == 0.0
    assert m.label == "—"


def test_recent_dominates():
    # 1 свежая победа после 3 поражений всё ещё считается отрицательным
    m = compute_momentum(["W", "L", "L", "L"])
    assert m.value < 0.5
