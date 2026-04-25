"""Тесты PlayerService."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from services.player_service import PlayerService


@pytest.mark.asyncio
async def test_player_profile_basic():
    sstats = AsyncMock()
    sstats.get_player.return_value = {
        "id": 7,
        "name": "Hero Hero",
        "position": "FW",
        "nationality": {"name": "Spain"},
        "age": 27,
        "team": {"name": "FC Top"},
    }
    sstats.get_player_events.return_value = []
    service = PlayerService(sstats)  # type: ignore[arg-type]
    p = await service.profile(7)
    assert p is not None
    assert p.team_name == "FC Top"
    assert p.position == "FW"


@pytest.mark.asyncio
async def test_player_missing_returns_none():
    sstats = AsyncMock()
    sstats.get_player.return_value = None
    service = PlayerService(sstats)  # type: ignore[arg-type]
    assert await service.profile(99) is None


@pytest.mark.asyncio
async def test_player_events_swallows_errors():
    sstats = AsyncMock()
    sstats.get_player.return_value = {"id": 1, "name": "X"}
    sstats.get_player_events.side_effect = RuntimeError("oops")
    service = PlayerService(sstats)  # type: ignore[arg-type]
    p = await service.profile(1)
    assert p is not None
    assert p.events == []
