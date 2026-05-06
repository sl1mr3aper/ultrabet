"""P0-11: Celery app для фоновых задач.

Зачем: бот сейчас держит self_learning_loop / expire_subscriptions_loop /
top_matches_precompute как long-running asyncio-task'и в одном процессе.
Это OK на одном инстансе, но не масштабируется горизонтально и опасно
при OOM (упал один loop — рискнул всем процессом).

Архитектура:
- ``celery_app`` — декларация Celery с broker=REDIS_URL.
- ``services.tasks`` — отдельный модуль с задачами (apply_async).
- Beat schedule в этом же файле — заменяет существующие
  asyncio-loop'ы детерминированным cron'ом.

Запуск (в продакшне через docker-compose):

    # worker:
    celery -A services.celery_app worker -l info -c 4

    # beat (отдельный процесс):
    celery -A services.celery_app beat -l info

В docker-compose добавить два сервиса (worker + beat) с тем же image,
что и основной бот; разделять процесс бота и worker'ов.

Замечания:
- Если ``celery`` не установлен (опциональная зависимость) — модуль
  отдаёт заглушку, у которой ``task()`` декоратор просто возвращает
  оригинальную функцию. Это позволяет писать tasks код один раз;
  локально/в тестах он работает синхронно через прямой вызов.
- broker_url по умолчанию читается из ``REDIS_URL`` через config.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any, TypeVar

F = TypeVar("F", bound=Callable[..., Any])


class _CeleryStub:
    """Заглушка на случай отсутствия установленного celery.

    Используется в тестах и при ``from services.celery_app import celery_app``
    в окружениях без celery (например, dev-машина).
    """

    def __init__(self, *_a: object, **_kw: object) -> None:
        self.tasks: dict[str, Callable[..., Any]] = {}
        self.conf = type(
            "_Conf", (), {"beat_schedule": {}, "timezone": "UTC"}
        )()

    def task(
        self,
        *t_a: object,
        **t_kw: object,
    ) -> Callable[[F], F]:
        bound_name = t_kw.get("name")

        def decorator(fn: F) -> F:
            name = str(bound_name) if bound_name else fn.__name__
            self.tasks[name] = fn
            return fn

        return decorator

    def autodiscover_tasks(self, *_a: object, **_kw: object) -> None:
        return None


def _build_app() -> Any:
    broker = os.environ.get("REDIS_URL") or "redis://localhost:6379/0"
    backend = os.environ.get("CELERY_RESULT_BACKEND") or broker
    try:
        from celery import Celery  # type: ignore[import-not-found]
    except ImportError:
        return _CeleryStub()

    app = Celery(
        "ultrabet",
        broker=broker,
        backend=backend,
        include=["services.tasks"],
    )
    app.conf.update(
        timezone="UTC",
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        result_expires=3600,
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        worker_prefetch_multiplier=1,
        broker_connection_retry_on_startup=True,
    )
    # Beat-расписание: заменяет asyncio-loop'ы.
    app.conf.beat_schedule = {
        "self-learner-every-30min": {
            "task": "services.tasks.run_self_learner",
            "schedule": 30 * 60,  # 30 минут
        },
        "secondary-calibrator-every-1h": {
            "task": "services.tasks.run_secondary_calibrator",
            "schedule": 60 * 60,
        },
        "expire-subscriptions-every-6h": {
            "task": "services.tasks.expire_subscriptions",
            "schedule": 6 * 60 * 60,
        },
        "clv-capture-every-1min": {
            "task": "services.tasks.capture_clv_for_pending",
            "schedule": 60.0,
        },
        "db-backup-every-6h": {
            "task": "services.tasks.run_db_backup",
            "schedule": 6 * 60 * 60,
        },
    }
    return app


celery_app = _build_app()


__all__ = ["celery_app"]
