"""Создаёт таблицы БД (CLI)."""

from __future__ import annotations

import asyncio

from loguru import logger

from config import get_settings
from db.database import Database
from utils.logger import setup_logging


async def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_file)
    db = Database(settings.database_url)
    await db.init_models()
    await db.close()
    logger.info("Done.")


if __name__ == "__main__":
    asyncio.run(main())
