"""Тесты SubscriptionService."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.repositories.user_repo import UserRepository
from services.subscription_service import SUBSCRIPTION_PLANS, PlanCode, SubscriptionService


def test_plans_present():
    for code in PlanCode:
        assert SUBSCRIPTION_PLANS[code.value].days > 0


def test_get_unknown_plan():
    assert SubscriptionService.get_plan("xyz") is None


@pytest.mark.asyncio
async def test_activate_extends_existing(session: AsyncSession):
    repo = UserRepository(session)
    user, _ = await repo.get_or_create(
        tg_id=1, username="t", first_name="t", last_name=None,
        language_code="ru", free_initial=0,
    )
    sub = SubscriptionService(session)

    plan_first = await sub.activate(user, "1m")
    assert plan_first
    end_first = user.subscription_until
    assert end_first is not None

    plan_second = await sub.activate(user, "1m")
    assert plan_second
    assert user.subscription_until is not None
    assert user.subscription_until > end_first


@pytest.mark.asyncio
async def test_is_active_now(session: AsyncSession):
    repo = UserRepository(session)
    user, _ = await repo.get_or_create(
        tg_id=2, username="t", first_name="t", last_name=None,
        language_code="ru", free_initial=0,
    )
    user.subscription_until = datetime.now(tz=UTC) + timedelta(days=1)
    assert SubscriptionService.is_active(user)
    user.subscription_until = datetime.now(tz=UTC) - timedelta(days=1)
    assert not SubscriptionService.is_active(user)
