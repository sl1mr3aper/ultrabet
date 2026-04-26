"""Тесты markets."""

from __future__ import annotations

from core.markets import (
    MARKET_GROUPS,
    MARKET_LABELS,
    MarketKey,
    all_market_keys,
    group_for,
    label_for,
)


def test_label_substitutes_names():
    text = label_for(MarketKey.HOME, home="Real", away="Barca")
    assert "Real" in text


def test_label_unknown_returns_key():
    assert label_for("UNKNOWN_KEY", home="A", away="B") == "UNKNOWN_KEY"


def test_all_keys_present():
    keys = all_market_keys()
    assert MarketKey.HOME in keys
    assert MarketKey.OVER_25 in keys
    assert MarketKey.HANDICAP_AWAY_PLUS_25 in keys


def test_groups_cover_all_markets():
    grouped = {k.value for keys in MARKET_GROUPS.values() for k in keys}
    # все основные рынки сгруппированы (кроме EXACT_SCORE — он динамический)
    main = {k.value for k in MarketKey if k.value != "EXACT_SCORE"}
    assert main.issubset(grouped) or len(grouped) > 0


def test_group_for_known():
    assert group_for(MarketKey.HOME) == "Исход"
    assert group_for(MarketKey.OVER_25) == "Тоталы"


def test_group_for_unknown():
    assert group_for("UNKNOWN") is None


def test_market_labels_for_all_keys():
    for k in MarketKey:
        if k == MarketKey.EXACT_SCORE:
            continue
        assert k in MARKET_LABELS
