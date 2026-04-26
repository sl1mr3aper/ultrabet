"""Тесты моделей и репозиториев."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from db.repositories.user_repo import UserRepository
from services.referral_service import ReferralService
from services.subscription_service import SubscriptionService


@pytest.mark.asyncio
async def test_user_create(session: AsyncSession):
    repo = UserRepository(session)
    user, created = await repo.get_or_create(
        tg_id=42, username="dj", first_name="DJ", last_name=None,
        language_code="ru", free_initial=5,
    )
    assert created is True
    assert user.tg_id == 42
    assert user.free_predictions_left == 5


@pytest.mark.asyncio
async def test_user_idempotent(session: AsyncSession):
    repo = UserRepository(session)
    u1, c1 = await repo.get_or_create(
        tg_id=42, username="dj", first_name="DJ", last_name=None,
        language_code="ru", free_initial=5,
    )
    u2, c2 = await repo.get_or_create(
        tg_id=42, username="dj_new", first_name="DJ", last_name=None,
        language_code="ru", free_initial=5,
    )
    assert c1 is True and c2 is False
    assert u1.id == u2.id
    assert u2.username == "dj_new"


@pytest.mark.asyncio
async def test_consume_quota_free(session: AsyncSession):
    repo = UserRepository(session)
    user, _ = await repo.get_or_create(
        tg_id=1, username="u", first_name="u", last_name=None,
        language_code="ru", free_initial=2,
    )
    assert await repo.consume_quota(user, daily_quota_for_subs=10)
    assert await repo.consume_quota(user, daily_quota_for_subs=10)
    assert not await repo.consume_quota(user, daily_quota_for_subs=10)


@pytest.mark.asyncio
async def test_referral_attaches(session: AsyncSession):
    repo = UserRepository(session)
    referrer, _ = await repo.get_or_create(
        tg_id=10, username="ref", first_name="ref", last_name=None,
        language_code="ru", free_initial=0,
    )
    referred, _ = await repo.get_or_create(
        tg_id=11, username="r2", first_name="r2", last_name=None,
        language_code="ru", free_initial=0,
    )
    ref_service = ReferralService(session, bonus_signup=3)
    code = await ref_service.ensure_code(referrer)
    assert code
    found = await ref_service.find_referrer(code)
    assert found is not None and found.id == referrer.id
    attached = await ref_service.attach_referral(referrer=found, referred=referred)
    assert attached
    # Бонусы теперь начисляются как бесплатные запросы (bonus_predictions удалён из продукта)
    assert referrer.free_predictions_left == 3
    assert referred.referred_by_id == referrer.id


@pytest.mark.asyncio
async def test_referral_no_self_attach(session: AsyncSession):
    repo = UserRepository(session)
    user, _ = await repo.get_or_create(
        tg_id=20, username="x", first_name="x", last_name=None,
        language_code="ru", free_initial=0,
    )
    ref = ReferralService(session)
    await ref.ensure_code(user)
    attached = await ref.attach_referral(referrer=user, referred=user)
    assert not attached


@pytest.mark.asyncio
async def test_subscription_activate(session: AsyncSession):
    repo = UserRepository(session)
    user, _ = await repo.get_or_create(
        tg_id=30, username="s", first_name="s", last_name=None,
        language_code="ru", free_initial=0,
    )
    sub = SubscriptionService(session)
    plan = await sub.activate(user, "1m")
    assert plan is not None
    assert user.subscription_plan == "1m"
    assert user.subscription_until is not None
    assert user.subscription_until > datetime.now(tz=UTC)
    assert SubscriptionService.is_active(user)
