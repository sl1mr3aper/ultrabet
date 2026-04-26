"""Тесты TeamService."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from services.team_service import TeamService


@pytest.mark.asyncio
async def test_team_profile_basic():
    sstats = AsyncMock()
    sstats.get_team.return_value = {
        "id": 1,
        "name": "FC Test",
        "glicko": {"rating": 1700},
        "country": {"name": "Spain"},
        "league": {"name": "La Liga"},
    }
    sstats.list_games.return_value = []
    service = TeamService(sstats)  # type: ignore[arg-type]
    profile = await service.profile(1)
    assert profile is not None
    assert profile.glicko_rating == 1700
    assert profile.country == "Spain"


@pytest.mark.asyncio
async def test_profile_handles_missing():
    sstats = AsyncMock()
    sstats.get_team.return_value = None
    service = TeamService(sstats)  # type: ignore[arg-type]
    assert await service.profile(1) is None


@pytest.mark.asyncio
async def test_search_calls_underlying_api():
    sstats = AsyncMock()
    sstats.search_teams.return_value = [{"id": 1, "name": "X"}]
    service = TeamService(sstats)  # type: ignore[arg-type]
    out = await service.search("x")
    assert len(out) == 1
