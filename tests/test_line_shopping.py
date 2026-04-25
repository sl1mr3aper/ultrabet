"""Тесты LineShoppingService."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from services.line_shopping import LineShoppingService, MarketSnapshot


@pytest.mark.asyncio
async def test_compare_picks_best_offer():
    sstats = AsyncMock()
    sstats.list_bookmakers.return_value = [
        {"id": 1, "name": "Bookie1"},
        {"id": 2, "name": "Bookie2"},
    ]
    sstats.get_prematch_odds.return_value = {
        "markets": [
            {
                "key": "1",
                "offers": [
                    {"bookmakerId": 1, "odds": 2.10},
                    {"bookmakerId": 2, "odds": 2.25},
                ],
            }
        ]
    }
    svc = LineShoppingService(sstats)  # type: ignore[arg-type]
    result = await svc.compare(123, ["1"])
    snap = result["1"]
    assert snap.best is not None
    assert snap.best.bookmaker_name == "Bookie2"
    assert snap.best.odds == 2.25
    assert snap.spread_pct > 0


def test_market_snapshot_empty_safe():
    snap = MarketSnapshot(market_key="1", selection="1", offers=[])
    assert snap.best is None
    assert snap.worst is None
    assert snap.spread_pct == 0.0


@pytest.mark.asyncio
async def test_compare_no_data():
    sstats = AsyncMock()
    sstats.list_bookmakers.return_value = []
    sstats.get_prematch_odds.return_value = None
    svc = LineShoppingService(sstats)  # type: ignore[arg-type]
    out = await svc.compare(1, ["1"])
    assert out == {}
