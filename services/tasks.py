"""Celery-задачи (skeletons).

Каждая задача — тонкая обёртка над уже существующим сервисом. В
обёртке мы:
1. Создаём свой event loop (Celery worker — sync-процесс).
2. Поднимаем DB / settings.
3. Делегируем работу async-сервису.
4. Возвращаем dict-сводку для observability.

Подключение:

    from services.celery_app import celery_app
    from services.tasks import *  # noqa  (authodiscover тоже работает)

В тестах задачи можно вызывать напрямую как обычные функции (apply_async
— не используем).
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from loguru import logger

from services.celery_app import celery_app


def _get_settings() -> Any:
    """Лениво — чтобы не падать в окружениях без BOT_TOKEN (например,
    тестах самого celery_app без секретов)."""
    from config import get_settings

    return get_settings()


@celery_app.task(name="services.tasks.run_self_learner")
def run_self_learner() -> dict[str, Any]:
    """Прогоняет один цикл self-learning (бывший self_learning_loop)."""
    logger.info("celery: run_self_learner started")

    async def _run() -> dict[str, Any]:
        settings = _get_settings()
        from db.database import Database
        from services.self_learner import SelfLearner

        db = Database(settings.database_url)
        await db.init_models()
        learner = SelfLearner(db.session_factory)
        try:
            return await learner.run_once()
        finally:
            await db.close()

    return asyncio.run(_run())


@celery_app.task(name="services.tasks.run_secondary_calibrator")
def run_secondary_calibrator() -> dict[str, Any]:
    """Прогоняет один цикл secondary pick calibrator."""
    logger.info("celery: run_secondary_calibrator started")

    async def _run() -> dict[str, Any]:
        settings = _get_settings()
        from db.database import Database
        from services.secondary_pick_calibrator import (
            SecondaryPickCalibrator,
        )

        db = Database(settings.database_url)
        await db.init_models()
        calibrator = SecondaryPickCalibrator(db.session_factory)
        try:
            updated = await calibrator.compute_adjustments()
            return {"adjustments_updated": updated}
        finally:
            await db.close()

    return asyncio.run(_run())


@celery_app.task(name="services.tasks.expire_subscriptions")
def expire_subscriptions() -> dict[str, Any]:
    """Помечает истёкшие подписки. Бывший expire_subscriptions_loop."""
    logger.info("celery: expire_subscriptions started")

    async def _run() -> dict[str, Any]:
        settings = _get_settings()
        from db.database import Database
        from services.subscription_service import SubscriptionService

        db = Database(settings.database_url)
        await db.init_models()
        try:
            svc = SubscriptionService(db.session_factory)
            return await svc.expire_overdue()
        finally:
            await db.close()

    return asyncio.run(_run())


@celery_app.task(name="services.tasks.capture_clv_for_pending")
def capture_clv_for_pending() -> dict[str, Any]:
    """Снимает closing odds Betfair для pending пиков."""
    logger.info("celery: capture_clv_for_pending started")
    if not os.environ.get("BETFAIR_APP_KEY"):
        logger.info("celery: BETFAIR_APP_KEY не задан, CLV пропущен")
        return {"skipped": True, "reason": "no_betfair_credentials"}
    return {"skipped": False, "reason": "needs_betfair_session_setup"}


@celery_app.task(name="services.tasks.run_db_backup")
def run_db_backup() -> dict[str, Any]:
    """Один проход бэкапа БД (используется вместо отдельного бэкап-сервиса)."""
    logger.info("celery: run_db_backup started")

    async def _run() -> dict[str, Any]:
        settings = _get_settings()
        from services.db_backup import run_backup_cycle

        path = await run_backup_cycle(
            database_url=settings.database_url,
            backup_dir=settings.backup_dir,
            retention_days=settings.backup_retention_days,
            s3_bucket=settings.backup_s3_bucket,
            s3_prefix=settings.backup_s3_prefix,
        )
        return {"backup_path": str(path)}

    return asyncio.run(_run())


@celery_app.task(name="services.tasks.sync_understat_xg")
def sync_understat_xg(league_slug: str = "EPL", season: str = "2025") -> dict[str, Any]:
    """Синхронизирует свежие xG-данные Understat в team_xg_samples."""
    logger.info(
        "celery: sync_understat_xg started ({} {})", league_slug, season
    )

    async def _run() -> dict[str, Any]:
        import aiohttp

        settings = _get_settings()
        from db.database import Database
        from services.understat_client import UnderstatClient
        from services.understat_xg_provider import UnderstatXgLoader

        db = Database(settings.database_url)
        await db.init_models()
        try:
            async with aiohttp.ClientSession() as http:
                client = UnderstatClient(http)
                loader = UnderstatXgLoader(
                    client=client, session_factory=db.session_factory
                )
                res = await loader.sync_league(
                    league_slug=league_slug, season=season
                )
                return {
                    "league": res.league_slug,
                    "season": res.season,
                    "fetched": res.fetched,
                    "inserted": res.inserted,
                    "skipped": res.skipped,
                }
        finally:
            await db.close()

    return asyncio.run(_run())


__all__ = [
    "capture_clv_for_pending",
    "expire_subscriptions",
    "run_db_backup",
    "run_secondary_calibrator",
    "run_self_learner",
    "sync_understat_xg",
]
