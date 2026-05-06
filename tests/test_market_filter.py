"""Тесты MarketFilter."""

from __future__ import annotations

from services.market_filter import MarketFilter


def test_market_filter_blocks_overestimated_market() -> None:
    """Модель ставит p=0.65, эмпирика 0.45 на 50 матчах → блок."""
    f = MarketFilter(market_hit_rates={"btts": (22, 50)})
    assert f.is_blocked("btts", model_prob=0.65) is True


def test_market_filter_does_not_block_well_calibrated_market() -> None:
    """Модель ставит 0.55, эмпирика 0.50 на 50 матчах → 5pp ниже порога 12pp."""
    f = MarketFilter(market_hit_rates={"home": (25, 50)})
    assert f.is_blocked("home", model_prob=0.55) is False


def test_market_filter_does_not_block_with_low_samples() -> None:
    """20 матчей < MIN_SAMPLES_BLOCK=30 → не блок."""
    f = MarketFilter(market_hit_rates={"over_2.5": (8, 20)})
    assert f.is_blocked("over_2.5", model_prob=0.65) is False


def test_market_filter_unknown_market_passes() -> None:
    f = MarketFilter()
    assert f.is_blocked("unknown_key", model_prob=0.99) is False


def test_market_filter_empirical_rate() -> None:
    f = MarketFilter(market_hit_rates={"home": (33, 50)})
    assert f.empirical_rate("home") == 0.66
    assert f.empirical_rate("nope") is None
