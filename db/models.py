"""SQLAlchemy модели."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(tz=UTC)


class Base(DeclarativeBase):
    """Базовый класс моделей."""


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tg_id: Mapped[int] = mapped_column(BigInteger, unique=True, index=True, nullable=False)
    username: Mapped[str | None] = mapped_column(String(64), nullable=True)
    first_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    last_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    language_code: Mapped[str | None] = mapped_column(String(8), nullable=True, default="ru")

    # Подписка
    subscription_plan: Mapped[str | None] = mapped_column(String(8), nullable=True)
    subscription_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    subscription_daily_quota: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Бесплатные / бонусные прогнозы
    free_predictions_left: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    bonus_predictions: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Дневной лимит
    daily_used: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    daily_reset_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Реферальная система
    referral_code: Mapped[str | None] = mapped_column(String(32), unique=True, nullable=True)
    referred_by_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    referral_signup_bonus_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    referral_sub_bonus_total: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Метаданные
    is_blocked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    badge: Mapped[str] = mapped_column(String(8), default="", nullable=False)
    strategy: Mapped[str | None] = mapped_column(String(16), default="balanced", nullable=True)
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        server_default=func.now(),
        nullable=False,
    )

    # Связи
    referrer: Mapped[User | None] = relationship(
        "User", remote_side="User.id", foreign_keys=[referred_by_id]
    )

    def display_name(self) -> str:
        if self.username:
            return f"@{self.username}"
        parts = [p for p in (self.first_name, self.last_name) if p]
        return " ".join(parts) or f"user{self.tg_id}"


class Referral(Base):
    __tablename__ = "referrals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    referrer_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    referred_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    subscription_plan: Mapped[str | None] = mapped_column(String(8), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now(), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("referrer_id", "referred_id", name="uq_referrer_referred"),
    )


class PaymentLog(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    plan_code: Mapped[str] = mapped_column(String(8), nullable=False)
    amount: Mapped[float] = mapped_column(nullable=False)
    currency: Mapped[str] = mapped_column(String(8), default="RUB", nullable=False)
    status: Mapped[str] = mapped_column(String(16), default="pending", nullable=False)
    provider: Mapped[str] = mapped_column(String(32), default="manual", nullable=False)
    external_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now(), nullable=False
    )
    confirmed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class PredictionLog(Base):
    __tablename__ = "prediction_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    game_id: Mapped[int] = mapped_column(BigInteger, index=True, nullable=False)
    home_name: Mapped[str] = mapped_column(String(128), nullable=False)
    away_name: Mapped[str] = mapped_column(String(128), nullable=False)
    league_name: Mapped[str | None] = mapped_column(String(128), nullable=True)
    home_xg: Mapped[float] = mapped_column(default=0.0, nullable=False)
    away_xg: Mapped[float] = mapped_column(default=0.0, nullable=False)
    home_rating: Mapped[float] = mapped_column(default=1500.0, nullable=False)
    away_rating: Mapped[float] = mapped_column(default=1500.0, nullable=False)
    payload: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("ix_predlogs_user_created", "user_id", "created_at"),)


class QueryHistory(Base):
    __tablename__ = "query_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    query_text: Mapped[str] = mapped_column(String(256), nullable=False)
    matched_game_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now(), nullable=False
    )


class Feedback(Base):
    __tablename__ = "feedback"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    text: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now(), nullable=False
    )


__all__ = [
    "Base",
    "Feedback",
    "PaymentLog",
    "PredictionLog",
    "QueryHistory",
    "Referral",
    "User",
]
