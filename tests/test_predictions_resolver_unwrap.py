"""Регрессионный тест на unwrap логику PredictionsResolver.

SStats `/Games/{id}` возвращает `{"game": {...}, "statistics": ..., ...}`,
а `_extract_score` ищет поля верхнего уровня. До фикса резолвер видел
None для всех счетов и pending пики никогда не закрывались.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from db.models import Base, PredictionOutcome
from services.predictions_resolver import PredictionsResolver, _unwrap_game


@pytest.fixture
async def session_factory() -> Any:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield factory
    await engine.dispose()


def test_unwrap_get_game_payload() -> None:
    """`/Games/{id}` payload — `{"game": {...inner...}, ...}`."""
    raw = {
        "game": {
            "id": 1543246,
            "homeFTResult": 2,
            "awayFTResult": 1,
            "status": 6,
        },
        "statistics": None,
        "lineups": None,
    }
    inner = _unwrap_game(raw)
    assert inner is not None
    assert inner["id"] == 1543246
    assert inner["homeFTResult"] == 2
    assert inner["awayFTResult"] == 1


def test_unwrap_flat_payload_passthrough() -> None:
    """`/Games/list` — плоский dict, без `game` ключа."""
    flat = {
        "id": 1543246,
        "homeFTResult": 2,
        "awayFTResult": 1,
    }
    assert _unwrap_game(flat) is flat


def test_unwrap_none_for_invalid() -> None:
    assert _unwrap_game(None) is None
    assert _unwrap_game([1, 2, 3]) is None
    assert _unwrap_game("not a dict") is None


def test_unwrap_falls_back_when_game_not_dict() -> None:
    raw = {"game": "lol-not-a-dict", "id": 999, "homeFTResult": 1, "awayFTResult": 0}
    inner = _unwrap_game(raw)
    assert inner is raw


@pytest.mark.asyncio
async def test_resolve_pending_now_settles_with_get_game_response(
    session_factory: Any,
) -> None:
    """С реалистичным `/Games/{id}` payload `hit` должен проставиться."""
    async with session_factory() as s:
        s.add_all([
            PredictionOutcome(
                game_id=1543246,
                market_key="1",  # home win
                predicted_probability=0.6,
                actual_odds=2.0,
                created_at=datetime.now(tz=UTC),
            ),
            PredictionOutcome(
                game_id=1543246,
                market_key="2",  # away win
                predicted_probability=0.2,
                actual_odds=4.0,
                created_at=datetime.now(tz=UTC),
            ),
        ])
        await s.commit()

    fake_client = AsyncMock()
    fake_client.get_game.return_value = {
        "game": {
            "id": 1543246,
            "date": "2025-01-15T18:00:00+00:00",
            "status": 6,
            "homeFTResult": 2,
            "awayFTResult": 1,
            "homeTeam": {"id": 1, "name": "Home"},
            "awayTeam": {"id": 2, "name": "Away"},
            "season": {"league": {"id": 100, "name": "Test League"}},
        },
        "statistics": None,
        "lineups": None,
    }

    resolver = PredictionsResolver(fake_client, session_factory)
    n = await resolver.resolve_pending()
    assert n == 2

    async with session_factory() as s:
        from sqlalchemy import select
        rows = list(
            (await s.scalars(select(PredictionOutcome).order_by(PredictionOutcome.market_key))).all()
        )
    # hit для рынка "1" (home win) при счёте 2:1 → True
    by_key = {r.market_key: r for r in rows}
    assert by_key["1"].hit is True
    # hit для рынка "2" (away win) при счёте 2:1 → False
    assert by_key["2"].hit is False


@pytest.mark.asyncio
async def test_resolve_pending_skips_unfinished_match(session_factory: Any) -> None:
    """Если SStats не вернул счёт (матч не закончен) — hit остаётся None."""
    async with session_factory() as s:
        s.add(PredictionOutcome(
            game_id=999,
            market_key="1",
            predicted_probability=0.6,
            created_at=datetime.now(tz=UTC),
        ))
        await s.commit()

    fake_client = AsyncMock()
    fake_client.get_game.return_value = {
        "game": {
            "id": 999,
            "status": 2,
            "statusName": "Not Started",
            "homeFTResult": None,
            "awayFTResult": None,
        },
    }

    resolver = PredictionsResolver(fake_client, session_factory)
    n = await resolver.resolve_pending()
    assert n == 0

    async with session_factory() as s:
        from sqlalchemy import select
        row = (await s.scalars(select(PredictionOutcome))).first()
        assert row is not None
        assert row.hit is None
