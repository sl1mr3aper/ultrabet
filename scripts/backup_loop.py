"""Бесконечный цикл бэкапов БД.

Используется сервисом ``backup`` в docker-compose.yml. Параметры читает
из переменных окружения:

- ``DATABASE_URL`` — строка подключения SQLAlchemy.
- ``BACKUP_DIR`` — директория для дампов (default: ``/var/backups/ultrabet``).
- ``BACKUP_INTERVAL_HOURS`` — интервал между запусками (default: 6).
- ``BACKUP_RETENTION_DAYS`` — срок хранения файлов (default: 7).
- ``BACKUP_S3_BUCKET`` — S3 бакет (опционально).
- ``BACKUP_S3_PREFIX`` — префикс ключа в S3 (default: ``ultrabet``).

Запуск вручную:
    python -m scripts.backup_loop
"""

from __future__ import annotations

import asyncio
import os
import sys

from loguru import logger

from services.db_backup import run_backup_cycle


def _env_int(name: str, default: int) -> int:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


async def main() -> int:
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        logger.error("DATABASE_URL не задан, бэкапить нечего")
        return 1

    backup_dir = os.environ.get("BACKUP_DIR", "/var/backups/ultrabet")
    interval_h = _env_int("BACKUP_INTERVAL_HOURS", 6)
    retention_d = _env_int("BACKUP_RETENTION_DAYS", 7)
    s3_bucket = os.environ.get("BACKUP_S3_BUCKET") or None
    s3_prefix = os.environ.get("BACKUP_S3_PREFIX", "ultrabet")

    logger.info(
        "backup_loop started: every {}h, retention {}d, s3={}",
        interval_h,
        retention_d,
        s3_bucket or "off",
    )

    while True:
        try:
            await run_backup_cycle(
                database_url=database_url,
                backup_dir=backup_dir,
                retention_days=retention_d,
                s3_bucket=s3_bucket,
                s3_prefix=s3_prefix,
            )
        except Exception as exc:
            logger.error("backup_cycle упал: {}", exc)

        await asyncio.sleep(max(60, interval_h * 3600))


if __name__ == "__main__":
    sys.exit(asyncio.run(main()) or 0)
