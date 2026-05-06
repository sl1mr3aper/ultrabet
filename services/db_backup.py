"""P0-3: бэкапы БД (SQLite или Postgres) c опциональным аплоадом в S3.

Архитектура:

- ``backup_database(...)`` — единичный дамп. Поддерживает sqlite и
  postgres-URL (через ``pg_dump`` если он есть в PATH; иначе fallback
  через ``pg_dump_via_psycopg`` неприменим в проде, поэтому требуется
  системный ``pg_dump``).
- ``cleanup_old_backups(...)`` — чистит старые файлы по сроку retention.
- ``upload_to_s3(...)`` — заливает файл в бакет, если задан
  ``settings.backup_s3_bucket`` и установлен ``boto3`` (опционально).

Зависимости:
- Python: ``boto3`` для S3 (опционально).
- System: ``pg_dump`` (входит в postgresql-client), нужен только для
  Postgres-режима.

Скрипты-обёртки:
- ``scripts/backup_loop.py`` — цикл бэкапов раз в N часов
  (используется в docker-compose сервисом ``backup``).
"""

from __future__ import annotations

import asyncio
import os
import shutil
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from loguru import logger


def _timestamp() -> str:
    return datetime.now(tz=UTC).strftime("%Y%m%d_%H%M%S")


def _parse_database_url(url: str) -> dict[str, Any]:
    """Лёгкий парсер DSN. Не пытается покрыть все случаи SQLAlchemy.

    Возвращает dict со scheme/path/host/port/user/password/dbname.
    """
    import urllib.parse as u

    # SQLAlchemy умеет ``sqlite+aiosqlite:///...``, но urllib понимает только
    # односложные схемы. Снимаем суффикс драйвера, оставив базовую схему.
    if "+" in url.split("://", 1)[0]:
        prefix, rest = url.split("://", 1)
        url = prefix.split("+", 1)[0] + "://" + rest

    parsed = u.urlparse(url)
    return {
        "scheme": parsed.scheme,
        "host": parsed.hostname,
        "port": parsed.port,
        "user": parsed.username,
        "password": parsed.password,
        "path": parsed.path,
        "dbname": parsed.path.lstrip("/") if parsed.scheme.startswith("postgres") else None,
    }


def _resolve_sqlite_file(raw_path: str) -> Path:
    """Приводит ``/data/bot.db`` или ``data/bot.db`` к абсолютному пути."""
    p = raw_path
    # SQLAlchemy: ``sqlite:///data/bot.db`` → urlparse даёт path=/data/bot.db
    if p.startswith("/") and not Path(p).is_absolute():
        p = p[1:]
    path = Path(p)
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def backup_database(
    database_url: str,
    backup_dir: str | Path,
) -> Path:
    """Создаёт сжатый дамп БД и возвращает путь к файлу.

    Для SQLite использует ``shutil.copy2`` + gzip (атомарно копирует файл).
    Для Postgres вызывает ``pg_dump -Fc`` (custom-format, бинарный).

    Бросает ``FileNotFoundError``, если БД не найдена; ``RuntimeError``,
    если ``pg_dump`` отсутствует или вернул ненулевой код.
    """
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)

    parsed = _parse_database_url(database_url)
    scheme = parsed["scheme"]
    ts = _timestamp()

    if scheme.startswith("sqlite"):
        src = _resolve_sqlite_file(parsed["path"])
        if not src.exists():
            raise FileNotFoundError(f"SQLite-файл не найден: {src}")
        dst = backup_dir / f"sqlite_{src.stem}_{ts}.db.gz"
        # Копируем + gzip-im через системную утилиту (gzip -9 быстрее zlib).
        tmp = backup_dir / f".__sqlite_{ts}.tmp"
        shutil.copy2(src, tmp)
        try:
            subprocess.run(
                ["gzip", "-9", "-c", str(tmp)],
                check=True,
                stdout=open(dst, "wb"),
            )
        finally:
            tmp.unlink(missing_ok=True)
        logger.info("DB backup (sqlite): {}", dst)
        return dst

    if scheme.startswith("postgres") or scheme.startswith("postgresql"):
        if shutil.which("pg_dump") is None:
            raise RuntimeError(
                "pg_dump не найден в PATH; установи postgresql-client"
            )
        dst = backup_dir / f"pg_{parsed['dbname'] or 'db'}_{ts}.dump"
        env = os.environ.copy()
        if parsed.get("password"):
            env["PGPASSWORD"] = str(parsed["password"])
        cmd = [
            "pg_dump",
            "-Fc",
            "-Z",
            "9",
            "-f",
            str(dst),
            "-h",
            str(parsed["host"] or "localhost"),
            "-p",
            str(parsed["port"] or 5432),
            "-U",
            str(parsed["user"] or "postgres"),
            "-d",
            str(parsed["dbname"]),
        ]
        result = subprocess.run(cmd, env=env, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"pg_dump упал ({result.returncode}): {result.stderr.strip()}"
            )
        logger.info("DB backup (postgres): {}", dst)
        return dst

    raise ValueError(f"неподдерживаемая схема БД для бэкапа: {scheme}")


def cleanup_old_backups(
    backup_dir: str | Path,
    *,
    retention_days: int,
) -> list[Path]:
    """Удаляет файлы старше retention_days. Возвращает список удалённых."""
    if retention_days <= 0:
        return []
    backup_dir = Path(backup_dir)
    if not backup_dir.exists():
        return []
    cutoff = datetime.now(tz=UTC) - timedelta(days=retention_days)
    removed: list[Path] = []
    for f in backup_dir.iterdir():
        if not f.is_file():
            continue
        # Игнорируем скрытые/служебные.
        if f.name.startswith("."):
            continue
        try:
            mtime = datetime.fromtimestamp(f.stat().st_mtime, tz=UTC)
        except OSError:
            continue
        if mtime < cutoff:
            f.unlink(missing_ok=True)
            removed.append(f)
    if removed:
        logger.info("DB backup cleanup: удалено {} файлов", len(removed))
    return removed


def upload_to_s3(
    file_path: str | Path,
    *,
    bucket: str,
    prefix: str = "ultrabet",
) -> str | None:
    """Заливает файл в S3 (если установлен boto3). Возвращает s3-URI."""
    file_path = Path(file_path)
    try:
        import boto3  # type: ignore[import-not-found]
    except ImportError:
        logger.warning(
            "boto3 не установлен; S3-upload пропущен (file={})", file_path
        )
        return None

    key = f"{prefix.rstrip('/')}/{file_path.name}"
    client = boto3.client("s3")
    client.upload_file(str(file_path), bucket, key)
    uri = f"s3://{bucket}/{key}"
    logger.info("DB backup uploaded: {}", uri)
    return uri


async def run_backup_cycle(
    *,
    database_url: str,
    backup_dir: str | Path,
    retention_days: int,
    s3_bucket: str | None = None,
    s3_prefix: str = "ultrabet",
) -> Path:
    """Один проход: дамп → cleanup → опционально S3."""
    loop = asyncio.get_running_loop()
    path = await loop.run_in_executor(
        None, lambda: backup_database(database_url, backup_dir)
    )
    await loop.run_in_executor(
        None,
        lambda: cleanup_old_backups(backup_dir, retention_days=retention_days),
    )
    if s3_bucket:
        await loop.run_in_executor(
            None,
            lambda: upload_to_s3(path, bucket=s3_bucket, prefix=s3_prefix),
        )
    return path


__all__ = [
    "backup_database",
    "cleanup_old_backups",
    "run_backup_cycle",
    "upload_to_s3",
]
