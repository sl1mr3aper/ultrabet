"""Тесты ProfileService."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import PredictionLog
from db.repositories.prediction_repo import PredictionLogRepository
from db.repositories.query_history_repo import QueryHistoryRepository
from db.repositories.user_repo import UserRepository
from services.profile_service import ProfileService


@pytest.mark.asyncio
async def test_empty_profile(session: AsyncSession):
    repo = UserRepository(session)
    user, _ = await repo.get_or_create(
        tg_id=42, username="x", first_name="X", last_name=None,
        language_code="ru", free_initial=0,
    )
    svc = ProfileService(session)
    p = await svc.get(user)
    assert p.total_predictions == 0
    assert p.total_queries == 0


@pytest.mark.asyncio
async def test_with_records(session: AsyncSession):
    repo = UserRepository(session)
    user, _ = await repo.get_or_create(
        tg_id=43, username="y", first_name="Y", last_name=None,
        language_code="ru", free_initial=0,
    )
    pred_repo = PredictionLogRepository(session)
    await pred_repo.add(
        PredictionLog(user_id=user.id, game_id=1, home_name="A", away_name="B",
                      league_name="L", home_xg=1.5, away_xg=1.0, home_rating=1500,
                      away_rating=1500)
    )
    history = QueryHistoryRepository(session)
    await history.add(user_id=user.id, query_text="A - B", matched_game_id=1, success=True)
    await history.add(user_id=user.id, query_text="C - D", matched_game_id=None, success=False)
    await session.commit()

    svc = ProfileService(session)
    p = await svc.get(user)
    assert p.total_predictions == 1
    assert p.total_queries == 2
    assert p.successful_queries == 1
