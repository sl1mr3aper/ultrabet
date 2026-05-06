"""Тесты DynamicBetfairMarketResolver — поиск market_id через listEvents
и listMarketCatalogue."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock

import pytest

from services.betfair_client import BetfairClient
from services.clv_tracker import DynamicBetfairMarketResolver


def _make_betfair_mock() -> BetfairClient:
    """BetfairClient с пустым __init__ через ``object.__new__``."""
    bf = object.__new__(BetfairClient)
    bf.list_events = AsyncMock()  # type: ignore[attr-defined]
    bf.list_market_catalogue = AsyncMock()  # type: ignore[attr-defined]
    bf.list_market_book = AsyncMock()  # type: ignore[attr-defined]
    return bf


@pytest.mark.asyncio
async def test_dynamic_resolver_finds_match_odds_home_selection() -> None:
    bf = _make_betfair_mock()
    bf.list_events.return_value = [  # type: ignore[attr-defined]
        {"event": {"id": "55001", "name": "Arsenal v Tottenham"}},
        {"event": {"id": "55002", "name": "Brighton v Chelsea"}},  # дистрактор
    ]
    bf.list_market_catalogue.return_value = [  # type: ignore[attr-defined]
        {
            "marketId": "1.234567",
            "runners": [
                {"selectionId": 100, "runnerName": "Arsenal"},
                {"selectionId": 200, "runnerName": "Tottenham"},
                {"selectionId": 300, "runnerName": "The Draw"},
            ],
        },
    ]

    async def lookup(game_id: int) -> Any:
        return ("Arsenal", "Tottenham", datetime.now(tz=UTC))

    resolver = DynamicBetfairMarketResolver(betfair=bf, match_lookup=lookup)
    ref = await resolver.resolve(game_id=42, market_key="1")

    assert ref is not None
    assert ref.market_id == "1.234567"
    assert ref.selection_id == 100  # Arsenal
    assert ref.market_type == "MATCH_ODDS"


@pytest.mark.asyncio
async def test_dynamic_resolver_finds_over_2_5() -> None:
    bf = _make_betfair_mock()
    bf.list_events.return_value = [  # type: ignore[attr-defined]
        {"event": {"id": "55001", "name": "Arsenal v Tottenham"}},
    ]
    bf.list_market_catalogue.return_value = [  # type: ignore[attr-defined]
        {
            "marketId": "1.999",
            "runners": [
                {"selectionId": 11, "runnerName": "Over 2.5 Goals"},
                {"selectionId": 22, "runnerName": "Under 2.5 Goals"},
            ],
        },
    ]

    async def lookup(_: int) -> Any:
        return ("Arsenal", "Tottenham", datetime.now(tz=UTC))

    resolver = DynamicBetfairMarketResolver(betfair=bf, match_lookup=lookup)
    ref = await resolver.resolve(game_id=42, market_key="tover_2.5")

    assert ref is not None
    assert ref.selection_id == 11
    assert ref.market_type == "OVER_UNDER_25"


@pytest.mark.asyncio
async def test_dynamic_resolver_finds_btts_yes() -> None:
    bf = _make_betfair_mock()
    bf.list_events.return_value = [  # type: ignore[attr-defined]
        {"event": {"id": "55001", "name": "Arsenal v Tottenham"}},
    ]
    bf.list_market_catalogue.return_value = [  # type: ignore[attr-defined]
        {
            "marketId": "1.btts",
            "runners": [
                {"selectionId": 70, "runnerName": "Yes"},
                {"selectionId": 80, "runnerName": "No"},
            ],
        },
    ]

    async def lookup(_: int) -> Any:
        return ("Arsenal", "Tottenham", datetime.now(tz=UTC))

    resolver = DynamicBetfairMarketResolver(betfair=bf, match_lookup=lookup)
    ref = await resolver.resolve(game_id=42, market_key="btts_yes")

    assert ref is not None
    assert ref.selection_id == 70
    assert ref.market_type == "BOTH_TEAMS_TO_SCORE"


@pytest.mark.asyncio
async def test_dynamic_resolver_returns_none_for_unknown_market_key() -> None:
    bf = _make_betfair_mock()

    async def lookup(_: int) -> Any:
        return ("Arsenal", "Tottenham", datetime.now(tz=UTC))

    resolver = DynamicBetfairMarketResolver(betfair=bf, match_lookup=lookup)
    ref = await resolver.resolve(game_id=42, market_key="exotic_market_key")

    assert ref is None
    bf.list_events.assert_not_called()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_dynamic_resolver_returns_none_when_no_event_match() -> None:
    bf = _make_betfair_mock()
    # Возвращает события, но ни одно не содержит наших команд
    bf.list_events.return_value = [  # type: ignore[attr-defined]
        {"event": {"id": "55003", "name": "Liverpool v Manchester City"}},
    ]

    async def lookup(_: int) -> Any:
        return ("Arsenal", "Tottenham", datetime.now(tz=UTC))

    resolver = DynamicBetfairMarketResolver(betfair=bf, match_lookup=lookup)
    ref = await resolver.resolve(game_id=42, market_key="1")

    assert ref is None


@pytest.mark.asyncio
async def test_dynamic_resolver_caches_event_id() -> None:
    bf = _make_betfair_mock()
    bf.list_events.return_value = [  # type: ignore[attr-defined]
        {"event": {"id": "55001", "name": "Arsenal v Tottenham"}},
    ]
    bf.list_market_catalogue.return_value = [  # type: ignore[attr-defined]
        {
            "marketId": "1.btts",
            "runners": [
                {"selectionId": 70, "runnerName": "Yes"},
                {"selectionId": 80, "runnerName": "No"},
            ],
        },
    ]

    async def lookup(_: int) -> Any:
        return ("Arsenal", "Tottenham", datetime.now(tz=UTC))

    resolver = DynamicBetfairMarketResolver(betfair=bf, match_lookup=lookup)
    # Два резолва для одного game_id — listEvents вызовется один раз
    await resolver.resolve(game_id=42, market_key="btts_yes")
    await resolver.resolve(game_id=42, market_key="btts_no")

    assert bf.list_events.call_count == 1  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_dynamic_resolver_returns_none_when_match_lookup_returns_none() -> None:
    bf = _make_betfair_mock()

    async def lookup(_: int) -> Any:
        return None

    resolver = DynamicBetfairMarketResolver(betfair=bf, match_lookup=lookup)
    ref = await resolver.resolve(game_id=42, market_key="1")

    assert ref is None
    bf.list_events.assert_not_called()  # type: ignore[attr-defined]


@pytest.mark.asyncio
async def test_dynamic_resolver_uses_time_window_in_listevents_filter() -> None:
    bf = _make_betfair_mock()
    bf.list_events.return_value = []  # type: ignore[attr-defined]

    fixed_dt = datetime(2026, 5, 10, 19, 0, tzinfo=UTC)

    async def lookup(_: int) -> Any:
        return ("A", "B", fixed_dt)

    resolver = DynamicBetfairMarketResolver(
        betfair=bf, match_lookup=lookup, time_window_hours=2
    )
    await resolver.resolve(game_id=42, market_key="1")

    bf.list_events.assert_called_once()  # type: ignore[attr-defined]
    kwargs = bf.list_events.call_args.kwargs  # type: ignore[attr-defined]
    window = kwargs.get("market_start_time")
    assert window is not None
    # ±2 часа от fixed_dt
    expected_from = (fixed_dt - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    expected_to = (fixed_dt + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert window["from"] == expected_from
    assert window["to"] == expected_to
