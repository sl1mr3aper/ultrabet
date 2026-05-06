"""Тесты для новых порогов value_engine: MIN_PROB_TAKE 0.45, MIN_FAIR_ODDS 1.51."""

from __future__ import annotations

from core.value_engine import (
    MIN_FAIR_ODDS,
    MIN_PROB_TAKE,
    MIN_VALUE_PCT_TAKE,
    score_pick,
)


def test_min_fair_odds_blocks_high_prob() -> None:
    """При p > 1/1.51 ≈ 0.66 → fair < 1.51 → не брать (даже если EV > 0)."""
    score = score_pick(market_key="home", probability=0.75, odds=1.40)
    assert score.fair_odds < MIN_FAIR_ODDS
    assert score.verdict == "не брать"
    assert score.accept is False


def test_min_prob_take_blocks_below_45pct() -> None:
    """При p=0.40 (был «брать» при 0.35) → теперь «осторожно» или «не брать»."""
    score = score_pick(market_key="under_2.5", probability=0.40, odds=2.50)
    assert score.probability < MIN_PROB_TAKE
    # 0.40 * 2.50 - 1 = 0.0 → EV=0 → не брать
    assert score.verdict in {"не брать", "осторожно"}


def test_take_at_60pct_with_strong_value() -> None:
    """p=0.60, odd=1.85 → fair=1.67, EV=11% → должен быть «брать»."""
    score = score_pick(market_key="home", probability=0.60, odds=1.85)
    assert score.fair_odds >= MIN_FAIR_ODDS
    assert score.probability >= MIN_PROB_TAKE
    assert score.ev_pct >= MIN_VALUE_PCT_TAKE
    assert score.verdict == "брать"


def test_caution_for_marginal_ev() -> None:
    """p=0.42, odd=2.45 → fair=2.38, EV=2.9% → «осторожно»."""
    score = score_pick(market_key="under_2.5", probability=0.42, odds=2.45)
    assert score.verdict == "осторожно"


def test_take_blocked_when_overheated_odds() -> None:
    """real_odds=10 при fair=1.5 → ratio=6.7 > 1.8 → real_odds игнорится → не берём."""
    score = score_pick(market_key="dnb_home", probability=0.67, odds=10.0)
    # Реальный кф будет отброшен sanity-фильтром. EV=0 → не брать.
    assert score.odds is None
    assert score.verdict == "не брать"
