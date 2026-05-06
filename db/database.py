"""Async подключение к SQLite (или другой БД)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from loguru import logger
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from db.models import Base


class Database:
    """Обёртка над AsyncEngine с фабрикой сессий."""

    def __init__(self, url: str, *, echo: bool = False) -> None:
        self._url = url
        # Для Postgres/MySQL задействуем connection pool с разумными дефолтами;
        # для SQLite (однопроцессный режим) pool-опции не применяются.
        engine_kwargs: dict = {
            "echo": echo,
            "future": True,
            "pool_pre_ping": True,
        }
        if url.startswith("sqlite"):
            # Для aiosqlite увеличиваем timeout ожидания лока (по умолчанию
            # 5с — на бот с конкурентными фоновыми задачами этого мало и
            # периодически бросается «database is locked»).
            engine_kwargs.update(
                {"connect_args": {"timeout": 60.0}},
            )
        else:
            engine_kwargs.update(
                {
                    "pool_size": 10,
                    "max_overflow": 10,
                    "pool_recycle": 3600,
                }
            )
        self._engine: AsyncEngine = create_async_engine(url, **engine_kwargs)
        if url.startswith("sqlite"):
            # Включаем WAL (writer не блокирует читателей) и NORMAL
            # synchronous — стандартная рекомендация SQLite для
            # высококонкурентной записи при сохранении устойчивости к
            # сбоям процесса.
            @event.listens_for(self._engine.sync_engine, "connect")
            def _sqlite_pragmas(dbapi_connection, _record) -> None:
                cursor = dbapi_connection.cursor()
                try:
                    cursor.execute("PRAGMA journal_mode=WAL")
                    cursor.execute("PRAGMA synchronous=NORMAL")
                    cursor.execute("PRAGMA busy_timeout=60000")
                    cursor.execute("PRAGMA foreign_keys=ON")
                finally:
                    cursor.close()
        self._session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
            self._engine,
            expire_on_commit=False,
            class_=AsyncSession,
        )

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    @property
    def session_factory(self) -> async_sessionmaker[AsyncSession]:
        return self._session_factory

    async def init_models(self) -> None:
        async with self._engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
            # Лёгкая идемпотентная миграция: добавляем колонки, появившиеся
            # после первой инициализации БД, чтобы не ронять бот при
            # апдейте кода без ручного `alembic upgrade`.
            #
            # Карта таблица → список (column, type_sqlite, type_postgres).
            # Для SQLite нужно проверять колонки через PRAGMA, для
            # Postgres — через information_schema и `ADD COLUMN IF NOT
            # EXISTS` (нативная поддержка с 9.6+).
            soft_migrations: dict[str, list[tuple[str, str, str]]] = {
                "users": [
                    ("subscription_expired_notified_at", "DATETIME", "TIMESTAMP"),
                ],
                "prediction_outcomes": [
                    ("closing_odds", "FLOAT", "DOUBLE PRECISION"),
                    ("clv", "FLOAT", "DOUBLE PRECISION"),
                    ("league_id", "BIGINT", "BIGINT"),
                    ("market_category", "VARCHAR(32)", "VARCHAR(32)"),
                ],
            }
            from sqlalchemy import text

            if self._url.startswith("sqlite"):
                for table_name, columns in soft_migrations.items():
                    try:
                        cols = await conn.execute(
                            text(f"PRAGMA table_info({table_name})"),
                        )
                        existing = {row[1] for row in cols.fetchall()}
                        if not existing:
                            continue
                        for col_name, col_type, _pg_type in columns:
                            if col_name not in existing:
                                await conn.execute(
                                    text(
                                        f"ALTER TABLE {table_name} "
                                        f"ADD COLUMN {col_name} {col_type}",
                                    ),
                                )
                                logger.info(
                                    "DB migration (sqlite): added {}.{}",
                                    table_name, col_name,
                                )
                    except Exception as exc:
                        logger.warning(
                            "Soft DB migration skipped for {}: {}",
                            table_name, exc,
                        )
            elif self._url.startswith("postgres") or self._url.startswith(
                "postgresql"
            ):
                for table_name, columns in soft_migrations.items():
                    try:
                        for col_name, _sqlite_type, pg_type in columns:
                            await conn.execute(
                                text(
                                    f"ALTER TABLE {table_name} "
                                    f"ADD COLUMN IF NOT EXISTS "
                                    f"{col_name} {pg_type}",
                                ),
                            )
                    except Exception as exc:
                        logger.warning(
                            "Soft DB migration (postgres) skipped for {}: {}",
                            table_name, exc,
                        )
        logger.info("Database initialized at {}", self._url)

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        session = self._session_factory()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def close(self) -> None:
        await self._engine.dispose()


def get_session_factory(database: Database) -> async_sessionmaker[AsyncSession]:
    return database.session_factory


__all__ = ["Database", "get_session_factory"]
