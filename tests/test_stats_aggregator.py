"""Тесты StatsAggregator."""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.repositories.user_repo import UserRepository
from services.stats_aggregator import StatsAggregator


@pytest.mark.asyncio
async def test_empty_state(session: AsyncSession):
    aggr = StatsAggregator(session)
    stats = await aggr.collect()
    assert stats.total_users == 0
    assert stats.query_success_rate == 0.0
    assert stats.conversion_pct == 0.0


@pytest.mark.asyncio
async def test_with_users(session: AsyncSession):
    repo = UserRepository(session)
    await repo.get_or_create(
        tg_id=1, username="a", first_name="A", last_name=None,
        language_code="ru", free_initial=0,
    )
    await repo.get_or_create(
        tg_id=2, username="b", first_name="B", last_name=None,
        language_code="ru", free_initial=0,
    )
    await session.commit()
    aggr = StatsAggregator(session)
    stats = await aggr.collect()
    assert stats.total_users == 2
    assert stats.paid_users == 0
