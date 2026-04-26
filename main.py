"""Точка входа бота."""

from __future__ import annotations

import asyncio
import signal

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from loguru import logger

from api.cache import APICache
from api.sstats_client import SStatsClient
from bot.handlers import get_root_router
from bot.middlewares import (
    BlockedGuardMiddleware,
    DbSessionMiddleware,
    ErrorMiddleware,
    ThrottlingMiddleware,
    UserMiddleware,
)
from config import Settings, get_settings
from db.database import Database
from services.analytics import AnalyticsService
from utils.logger import setup_logging


async def _set_commands(bot: Bot) -> None:
    from aiogram.types import BotCommand

    commands = [
        BotCommand(command="start", description="Запуск/главное меню"),
        BotCommand(command="menu", description="Главное меню"),
        BotCommand(command="match", description="Прогноз: Команда1 - Команда2"),
        BotCommand(command="matches", description="Подборки матчей: today/tomorrow/live"),
        BotCommand(command="league", description="Лига и её матчи"),
        BotCommand(command="standings", description="Турнирная таблица"),
        BotCommand(command="balance", description="Баланс прогнозов"),
        BotCommand(command="subscribe", description="Подписки"),
        BotCommand(command="referral", description="Реферальная программа"),
        BotCommand(command="feedback", description="Оставить отзыв"),
        BotCommand(command="help", description="Помощь"),
    ]
    await bot.set_my_commands(commands)


async def main() -> None:
    settings: Settings = get_settings()
    setup_logging(settings.log_level, settings.log_file)
    logger.info("Запускаю UltraBet, env={}", settings.bot_username)

    database = Database(settings.database_url)
    await database.init_models()

    http = aiohttp.ClientSession()
    cache = APICache()
    sstats = SStatsClient(
        http,
        api_key=settings.sstats_api_key_value,
        base_url=settings.sstats_base_url,
        timeout=settings.sstats_timeout,
        max_retries=settings.sstats_max_retries,
        cache=cache,
    )

    bot = Bot(
        token=settings.bot_token_value,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
    )
    from bot.context import services as _services
    _services.settings = settings
    _services.sstats = sstats
    _services.session_factory = database.session_factory
    _services.analytics = AnalyticsService()

    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher["settings"] = settings
    dispatcher["sstats"] = sstats
    dispatcher["session_factory"] = database.session_factory

    error_mw = ErrorMiddleware()
    db_mw = DbSessionMiddleware(database.session_factory)
    user_mw = UserMiddleware(free_initial=settings.free_predictions_initial)
    throttle_mw = ThrottlingMiddleware(rate=0.4)
    blocked_mw = BlockedGuardMiddleware()

    dispatcher.update.middleware(error_mw)
    dispatcher.message.middleware(db_mw)
    dispatcher.message.middleware(user_mw)
    dispatcher.message.middleware(blocked_mw)
    dispatcher.message.middleware(throttle_mw)
    dispatcher.callback_query.middleware(db_mw)
    dispatcher.callback_query.middleware(user_mw)
    dispatcher.callback_query.middleware(blocked_mw)
    dispatcher.callback_query.middleware(throttle_mw)

    dispatcher.include_router(get_root_router())

    stop_event = asyncio.Event()

    def _shutdown(*_: object) -> None:
        logger.info("Получен сигнал завершения...")
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _shutdown)
        except NotImplementedError:
            pass

    await _set_commands(bot)
    logger.info("Long polling started")

    from bot.handlers.subscription import expire_subscriptions_loop
    expire_task = asyncio.create_task(expire_subscriptions_loop(bot, 3600))

    polling_task = asyncio.create_task(dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types()))
    stop_task = asyncio.create_task(stop_event.wait())
    await asyncio.wait({polling_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
    expire_task.cancel()

    logger.info("Завершаю работу...")
    await dispatcher.stop_polling()
    polling_task.cancel()
    try:
        await polling_task
    except (asyncio.CancelledError, Exception):
        pass

    await bot.session.close()
    await http.close()
    await database.close()
    logger.info("Бот остановлен.")


if __name__ == "__main__":
    asyncio.run(main())
