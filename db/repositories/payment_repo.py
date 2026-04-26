"""Репозиторий платежей."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import PaymentLog


class PaymentRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        *,
        user_id: int,
        plan_code: str,
        amount: float,
        currency: str = "RUB",
        provider: str = "manual",
        external_id: str | None = None,
    ) -> PaymentLog:
        record = PaymentLog(
            user_id=user_id,
            plan_code=plan_code,
            amount=amount,
            currency=currency,
            provider=provider,
            external_id=external_id,
        )
        self._session.add(record)
        await self._session.flush()
        return record

    async def confirm(self, payment_id: int) -> PaymentLog | None:
        record = await self._session.get(PaymentLog, payment_id)
        if record is None:
            return None
        record.status = "confirmed"
        record.confirmed_at = datetime.now(tz=UTC)
        await self._session.flush()
        return record

    async def list_for_user(self, user_id: int, *, limit: int = 20) -> list[PaymentLog]:
        result = await self._session.scalars(
            select(PaymentLog)
            .where(PaymentLog.user_id == user_id)
            .order_by(desc(PaymentLog.created_at))
            .limit(limit)
        )
        return list(result)


__all__ = ["PaymentRepository"]
