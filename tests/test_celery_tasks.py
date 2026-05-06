"""Тесты для services/celery_app + services/tasks.

Не требуют установленного celery — модули падают на _CeleryStub fallback.
Прогоняют только проверку структуры и тонкого wrapping'а.
"""

from __future__ import annotations

import importlib

import pytest


def test_celery_app_loads() -> None:
    from services.celery_app import celery_app

    # Либо реальный Celery, либо stub — оба валидны.
    assert celery_app is not None
    # У stub есть атрибут tasks, у Celery — registered tasks через app.tasks
    assert hasattr(celery_app, "task")
    assert hasattr(celery_app, "conf")


def test_beat_schedule_present_when_celery_available() -> None:
    """Если celery установлен — должен быть beat_schedule."""
    pytest.importorskip("celery")
    from services.celery_app import celery_app

    schedule = getattr(celery_app.conf, "beat_schedule", None)
    assert isinstance(schedule, dict)
    expected_keys = {
        "self-learner-every-30min",
        "secondary-calibrator-every-1h",
        "expire-subscriptions-every-6h",
        "clv-capture-every-1min",
        "db-backup-every-6h",
    }
    assert expected_keys.issubset(set(schedule.keys()))


def test_tasks_module_importable() -> None:
    tasks = importlib.import_module("services.tasks")
    # Все ключевые функции экспортированы.
    for name in (
        "run_self_learner",
        "run_secondary_calibrator",
        "expire_subscriptions",
        "capture_clv_for_pending",
        "run_db_backup",
        "sync_understat_xg",
    ):
        assert hasattr(tasks, name), f"missing task: {name}"


def test_capture_clv_skips_without_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BETFAIR_APP_KEY", raising=False)
    from services.tasks import capture_clv_for_pending

    # Реальный celery вернул бы AsyncResult, но stub возвращает функцию.
    res = capture_clv_for_pending()
    assert isinstance(res, dict)
    assert res.get("skipped") is True
