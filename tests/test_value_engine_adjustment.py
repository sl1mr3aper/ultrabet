"""Тесты adjustment_factor в score_pick / select_best_pick."""

from __future__ import annotations

import pytest

from core.value_engine import score_pick, select_best_pick


def test_score_pick_no_adjustment_default() -> None:
    """factor=1.0 по умолчанию — поведение неизменно."""
    p = score_pick(market_key="home", probability=0.55, odds=2.0)
    assert p.probability == pytest.approx(0.55)


def test_score_pick_with_factor_increases_prob() -> None:
    """Adjustment factor 1.2 поднимает probability с 0.55 до 0.66."""
    p = score_pick(
        market_key="home",
        probability=0.55,
        odds=2.0,
        adjustment_factor=1.2,
    )
    assert p.probability == pytest.approx(0.66)


def test_score_pick_factor_clamped_to_max() -> None:
    """factor выше 1.5 зажимается в 1.5 (бережёт от перегрева)."""
    p = score_pick(
        market_key="home",
        probability=0.55,
        odds=2.0,
        adjustment_factor=10.0,
    )
    # 0.55 * 1.5 = 0.825
    assert p.probability == pytest.approx(0.825)


def test_score_pick_factor_clamped_to_min() -> None:
    """factor ниже 0.5 зажимается в 0.5."""
    p = score_pick(
        market_key="home",
        probability=0.55,
        odds=2.0,
        adjustment_factor=0.1,
    )
    # 0.55 * 0.5 = 0.275
    assert p.probability == pytest.approx(0.275)


def test_score_pick_capped_at_max_prob_sane() -> None:
    """Даже с factor=1.5 итоговая вероятность не превышает MAX_PROB_SANE."""
    p = score_pick(
        market_key="home",
        probability=0.95,
        odds=1.5,
        adjustment_factor=1.5,
    )
    # 0.95 * 1.5 = 1.425 → cap to MAX_PROB_SANE (=0.97)
    from core.value_engine import MAX_PROB_SANE
    assert p.probability <= MAX_PROB_SANE


def test_score_pick_factor_changes_verdict() -> None:
    """Adjustment может изменить «не брать» → «брать» (если EV > 7%)."""
    # base: p=0.51, odds=2.10 → EV = 0.51*2.10-1 = 7.1% (~брать)
    # с factor=0.85: p=0.4335, odds=2.10 → EV ≈ -8.9% (не брать)
    p_low = score_pick(
        market_key="home",
        probability=0.51,
        odds=2.10,
        adjustment_factor=0.85,
    )
    assert p_low.verdict == "не брать"

    # с factor=1.15: p=0.5865, odds=2.10 → EV ≈ 23% (брать)
    p_high = score_pick(
        market_key="home",
        probability=0.51,
        odds=2.10,
        adjustment_factor=1.15,
    )
    assert p_high.verdict == "брать"


def test_select_best_pick_uses_adjustment_map() -> None:
    """select_best_pick применяет adjustment_map через score_pick."""
    # p=0.60, odds=2.10 → EV=26%, выше MIN_PROB_TAKE и MIN_VALUE_PCT_TAKE
    probs = {"home": 0.60, "draw": 0.25, "away": 0.15}
    odds = {"home": 2.10, "draw": 3.20, "away": 4.50}
    # без adjustment: home — главный кандидат, verdict="брать"
    no_adj = select_best_pick(probs, odds)
    assert no_adj is not None
    assert no_adj.market_key == "home"
    assert no_adj.verdict == "брать"

    # С adjustment 0.7 для home → p=0.42, EV отрицательный → не брать
    adj_map = {"home": 0.7}
    with_adj = select_best_pick(probs, odds, adjustment_map=adj_map)
    # home теперь p=0.42, EV ≈ −12% → не брать.
    # Других пиков с verdict="брать" нет → None.
    if with_adj is not None:
        assert with_adj.market_key != "home" or with_adj.verdict != "брать"
