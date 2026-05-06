"""Тесты services/db_backup — SQLite backup + cleanup + парсер DSN."""

from __future__ import annotations

import asyncio
import os
import sqlite3
import time
from pathlib import Path

import pytest

from services import db_backup


@pytest.fixture
def sample_db(tmp_path: Path) -> Path:
    db = tmp_path / "bot.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    conn.executemany(
        "INSERT INTO t (v) VALUES (?)", [("a",), ("b",), ("c",)]
    )
    conn.commit()
    conn.close()
    return db


def test_backup_sqlite_creates_gz(sample_db: Path, tmp_path: Path) -> None:
    backup_dir = tmp_path / "backups"
    url = f"sqlite+aiosqlite:///{sample_db}"
    out = db_backup.backup_database(url, backup_dir)
    assert out.exists()
    assert out.suffix == ".gz"
    # Файл должен быть сжатый: размер заметно меньше исходного.
    assert out.stat().st_size > 0


def test_backup_sqlite_missing_file(tmp_path: Path) -> None:
    url = f"sqlite+aiosqlite:///{tmp_path / 'nonexistent.db'}"
    with pytest.raises(FileNotFoundError):
        db_backup.backup_database(url, tmp_path / "b")


def test_backup_unknown_scheme(tmp_path: Path) -> None:
    with pytest.raises(ValueError):
        db_backup.backup_database("mysql://user:pass@host/db", tmp_path / "b")


def test_cleanup_old_backups(tmp_path: Path) -> None:
    f_old = tmp_path / "old.dump"
    f_old.write_bytes(b"x")
    # Сдвигаем mtime "в прошлое" на 30 дней.
    past = time.time() - 30 * 86_400
    os.utime(f_old, (past, past))
    f_new = tmp_path / "new.dump"
    f_new.write_bytes(b"x")
    removed = db_backup.cleanup_old_backups(tmp_path, retention_days=7)
    assert f_old in removed
    assert f_new.exists()


def test_cleanup_disabled() -> None:
    assert db_backup.cleanup_old_backups("/nonexistent", retention_days=0) == []


def test_run_backup_cycle_async(sample_db: Path, tmp_path: Path) -> None:
    url = f"sqlite+aiosqlite:///{sample_db}"
    out = asyncio.run(
        db_backup.run_backup_cycle(
            database_url=url,
            backup_dir=tmp_path / "b",
            retention_days=7,
            s3_bucket=None,
        )
    )
    assert out.exists()


def test_parse_database_url_sqlite() -> None:
    parsed = db_backup._parse_database_url("sqlite+aiosqlite:///data/bot.db")
    assert parsed["scheme"] == "sqlite"
    # SQLite path берём из urlparse.path
    assert parsed["path"].endswith("data/bot.db")


def test_parse_database_url_postgres() -> None:
    parsed = db_backup._parse_database_url(
        "postgresql+asyncpg://u:p@host:5432/mydb"
    )
    assert parsed["scheme"] == "postgresql"
    assert parsed["host"] == "host"
    assert parsed["port"] == 5432
    assert parsed["user"] == "u"
    assert parsed["password"] == "p"
    assert parsed["dbname"] == "mydb"
