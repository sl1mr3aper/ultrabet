"""Тесты LeagueService с mocked SStats."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from services.league_service import LeagueService


@pytest.mark.asyncio
async def test_list_all():
    sstats = AsyncMock()
    sstats.list_leagues.return_value = [
        {"id": 1, "name": "Premier League", "country": {"name": "England"}},
        {"id": 2, "name": "La Liga", "country": {"name": "Spain"}},
        {"id": "bad", "name": "Skip"},
    ]
    service = LeagueService(sstats)  # type: ignore[arg-type]
    result = await service.list_all()
    assert len(result) == 2
    names = [r.name for r in result]
    assert "Premier League" in names
    assert "La Liga" in names


@pytest.mark.asyncio
async def test_search_filter_lowercase():
    sstats = AsyncMock()
    sstats.list_leagues.return_value = [
        {"id": 1, "name": "Premier League", "country": {"name": "England"}},
        {"id": 2, "name": "La Liga", "country": {"name": "Spain"}},
    ]
    service = LeagueService(sstats)  # type: ignore[arg-type]
    res = await service.search("premier")
    assert len(res) == 1
    assert res[0].name == "Premier League"


@pytest.mark.asyncio
async def test_current_season_returns_uid():
    sstats = AsyncMock()
    sstats.ls_seasons.return_value = [{"uid": "s1", "id": 99}]
    service = LeagueService(sstats)  # type: ignore[arg-type]
    uid = await service.current_season_id(1)
    assert uid == "s1"


@pytest.mark.asyncio
async def test_current_season_none_when_empty():
    sstats = AsyncMock()
    sstats.ls_seasons.return_value = []
    service = LeagueService(sstats)  # type: ignore[arg-type]
    assert await service.current_season_id(1) is None


@pytest.mark.asyncio
async def test_profits_swallows_errors():
    sstats = AsyncMock()
    sstats.get_profits.side_effect = RuntimeError("boom")
    service = LeagueService(sstats)  # type: ignore[arg-type]
    assert await service.profits(1) is None


@pytest.mark.asyncio
async def test_standings_chained():
    sstats = AsyncMock()
    sstats.ls_seasons.return_value = [{"uid": "s1"}]
    sstats.get_standings.return_value: Any = {"standings": []}
    service = LeagueService(sstats)  # type: ignore[arg-type]
    result = await service.standings(1)
    assert result == {"standings": []}
    sstats.get_standings.assert_awaited_once_with("s1")
