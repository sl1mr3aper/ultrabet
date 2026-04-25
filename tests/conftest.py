"""Pytest fixtures."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

os.environ.setdefault("BOT_TOKEN", "123456:test_token")
os.environ.setdefault("SSTATS_API_KEY", "")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from db.database import Database


@pytest_asyncio.fixture
async def database() -> AsyncIterator[Database]:
    db = Database("sqlite+aiosqlite:///:memory:")
    await db.init_models()
    try:
        yield db
    finally:
        await db.close()


@pytest_asyncio.fixture
async def session(database: Database) -> AsyncIterator[AsyncSession]:
    async with database.session_factory() as s:
        yield s
        await s.rollback()
