"""Точка входа бота."""

from __future__ import annotations

import asyncio
import os
import signal
from typing import Any

import aiohttp
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
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
from services.external_odds import NBBetClient
from services.observability import (
    get_metrics,
    init_sentry,
    start_prometheus_server,
)
from services.self_learner import SelfLearner
from utils.logger import setup_logging


async def _set_commands(bot: Bot) -> None:
    from aiogram.types import BotCommand

    # UX-политика: в чат-меню выставляем только /start. Все разделы — кнопками.
    commands = [
        BotCommand(command="start", description="Главное меню"),
    ]
    await bot.set_my_commands(commands)


async def main() -> None:
    settings: Settings = get_settings()
    setup_logging(settings.log_level, settings.log_file)
    # Observability: Sentry + Prometheus инициализируются "мягко" —
    # если SDK / DSN не заданы, всё работает в no-op режиме без ошибок.
    init_sentry(settings)
    start_prometheus_server(settings)
    metrics = get_metrics()
    metrics.bot_started.inc()
    logger.info("Запускаю UltraBet, env={}", settings.bot_username)

    database = Database(settings.database_url)
    await database.init_models()

    # Оптимизированный HTTP-клиент: больше keepalive-коннекций, кэш DNS,
    # увеличенный пул per-host (SStats — основной источник, его и грузим).
    _connector = aiohttp.TCPConnector(
        limit=200,            # общий пул коннекций
        limit_per_host=50,    # на один хост (SStats)
        ttl_dns_cache=600,    # 10 минут DNS-кэш
        use_dns_cache=True,
        keepalive_timeout=75, # дольше держим открытыми
        enable_cleanup_closed=True,
    )
    http = aiohttp.ClientSession(
        connector=_connector,
        timeout=aiohttp.ClientTimeout(total=30, connect=10),
    )
    cache = APICache()
    sstats = SStatsClient(
        http,
        api_key=settings.sstats_api_key_value,
        base_url=settings.sstats_base_url,
        timeout=settings.sstats_timeout,
        max_retries=settings.sstats_max_retries,
        cache=cache,
    )

    # Прокси для Telegram API (SOCKS5 от xray)
    # Читаем PROXY_URL из .env файла или из переменных окружения
    proxy_url = os.getenv("PROXY_URL", "")
    if not proxy_url:
        # Пробуем прочитать напрямую из .env
        import pathlib
        _env_path = pathlib.Path(__file__).resolve().parent / ".env"
        if _env_path.exists():
            for _line in _env_path.read_text(encoding="utf-8").splitlines():
                _line = _line.strip()
                if _line.startswith("PROXY_URL="):
                    proxy_url = _line.split("=", 1)[1].strip().strip('"').strip("'")
                    break

    if proxy_url:
        bot_session = AiohttpSession(proxy=proxy_url)
        logger.info("Telegram proxy enabled: {}", proxy_url)
    else:
        bot_session = AiohttpSession()
        logger.warning("PROXY_URL не задан — подключение к Telegram напрямую")

    bot = Bot(
        token=settings.bot_token_value,
        default=DefaultBotProperties(parse_mode=ParseMode.MARKDOWN),
        session=bot_session,
    )
    from bot.context import services as _services
    from services.cache_warmer import CacheWarmer
    from services.calibration_service import CalibrationService
    from services.history_backfill import HistoryBackfillService
    from services.kv_cache import KVCache
    from services.league_aggregate_service import LeagueAggregateService
    from services.league_standings import LeagueStandingsService
    from services.predictions_resolver import PredictionsResolver
    from services.topmatches_precompute import TopMatchesPrecompute

    _services.settings = settings
    _services.kv_cache = KVCache(redis_url=getattr(settings, "redis_url", None))
    _services.sstats = sstats
    _services.session_factory = database.session_factory
    _services.analytics = AnalyticsService()
    _services.self_learner = SelfLearner(database.session_factory)
    _services.nb_bet_client = NBBetClient()
    _services.history_backfill = HistoryBackfillService(
        sstats, database.session_factory
    )
    _services.predictions_resolver = PredictionsResolver(
        sstats, database.session_factory
    )
    _services.calibration = CalibrationService(database.session_factory)
    _services.cache_warmer = CacheWarmer(sstats)
    _services.league_standings = LeagueStandingsService(
        sstats, database.session_factory,
    )
    _services.league_aggregates = LeagueAggregateService(database.session_factory)
    # SecondaryPickCalibrator: считает adjustment_factor по истории всех
    # пиков (`match_pick_history`). Применяется к probabilities в
    # PredictionService — корректирует модель на основе эмпирики.
    from services.pick_adjustment_cache import PickAdjustmentCache
    _services.pick_adjustments = PickAdjustmentCache(
        database.session_factory,
        refresh_interval_seconds=3600,  # пересчёт раз в час
    )

    # P0-9: общий провайдер реального xG из Understat (shot-based).
    # Активен, если в `team_xg_samples` есть данные (заполняются через
    # services.tasks.sync_understat_xg / scripts.sync_understat).
    from services.understat_xg_provider import UnderstatXgProvider
    _services.understat_xg_provider = UnderstatXgProvider(
        session_factory=database.session_factory,
    )

    def _build_prediction_service() -> Any:
        from core.value_calculator import ValueCalculator
        from services.odds_parser import OddsParser
        from services.prediction_service import PredictionService
        return PredictionService(
            sstats,
            value_calculator=ValueCalculator(),
            odds_parser=OddsParser(),
            self_learner=_services.self_learner,
            nb_bet_client=_services.nb_bet_client,
            understat_xg_provider=_services.understat_xg_provider,
        )

    _services.topmatches_precompute = TopMatchesPrecompute(
        sstats,
        _build_prediction_service,
        session_factory=database.session_factory,
    )

    # Опциональный AI-уточнитель главного прогноза (Gemini, free tier).
    _gemini_key = settings.gemini_api_key_value
    if _gemini_key:
        from services.ai_refiner import GeminiRefiner
        _services.ai_refiner = GeminiRefiner(
            api_key=_gemini_key,
            model=settings.gemini_model,
            timeout=settings.gemini_timeout,
        )
        logger.info("Gemini AI-refiner enabled (model={})", settings.gemini_model)
    else:
        _services.ai_refiner = None

    dispatcher = Dispatcher(storage=MemoryStorage())
    dispatcher["settings"] = settings
    dispatcher["sstats"] = sstats
    dispatcher["session_factory"] = database.session_factory

    error_mw = ErrorMiddleware()
    db_mw = DbSessionMiddleware(database.session_factory)
    admin_ids = settings.admin_ids if isinstance(settings.admin_ids, list) else []
    user_mw = UserMiddleware(
        free_initial=settings.free_predictions_initial,
        admin_ids=admin_ids,
    )
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

    # Прогрев горячих эндпоинтов на старте: список лиг + матчи на
    # сегодня/завтра. Кэш SStats — in-memory с TTL 24ч (лиги) и 5 мин
    # (матчи), поэтому первый клик пользователя по «Лиги/Сегодня/Завтра»
    # будет мгновенным. Делается параллельно, тихо игнорируем ошибки.
    async def _initial_warm() -> None:
        sstats = _services.sstats  # type: ignore[union-attr]
        settings = _services.settings  # type: ignore[union-attr]
        from datetime import datetime, timedelta, timezone
        try:
            tz = timezone(timedelta(hours=settings.timezone_offset))
            today = datetime.now(tz=tz).strftime("%Y-%m-%d")
            tomorrow = (
                datetime.now(tz=tz) + timedelta(days=1)
            ).strftime("%Y-%m-%d")
            await asyncio.gather(
                sstats.list_leagues(),
                sstats.list_games(
                    date=today,
                    limit=200,
                    time_zone=settings.timezone_offset,
                ),
                sstats.list_games(
                    date=tomorrow,
                    limit=200,
                    time_zone=settings.timezone_offset,
                ),
                return_exceptions=True,
            )
            logger.info("Initial cache warm done (leagues + today + tomorrow)")
        except Exception as exc:
            logger.debug("initial warm failed: {}", exc)
    _warm_task = asyncio.create_task(_initial_warm())  # noqa: RUF006

    from bot.handlers.subscription import expire_subscriptions_loop
    expire_task = asyncio.create_task(expire_subscriptions_loop(bot, 3600))

    async def _self_learning_loop() -> None:
        # Раз в 6 часов оцениваем новые результаты и пересчитываем калибровку.
        # В этом же loop'е резолвим match_pick_history (все ~40 пиков матча)
        # и пересчитываем adjustment_factor через SecondaryPickCalibrator.
        while True:
            try:
                await _services.self_learner.evaluate_pending()  # type: ignore[union-attr]
                await _services.self_learner.compute_snapshot()  # type: ignore[union-attr]
                from services.match_pick_history import (
                    resolve_pending_picks,
                )
                from services.secondary_pick_calibrator import (
                    SecondaryPickCalibrator,
                )

                resolved_n = await resolve_pending_picks(
                    database.session_factory,
                )
                if resolved_n > 0:
                    logger.info(
                        "match_pick_history: resolved {} picks",
                        resolved_n,
                    )
                calib = SecondaryPickCalibrator(database.session_factory)
                stats = await calib.compute_adjustments()
                if stats and _services.pick_adjustments is not None:
                    await _services.pick_adjustments.refresh_now()
            except Exception as exc:
                logger.warning("self-learning loop error: {}", exc)
            await asyncio.sleep(6 * 3600)

    async def _history_backfill_loop() -> None:
        # P0-1: каждые 6 ч тянем последние сыгранные матчи во все лиги.
        # Первый проход — через 60 с после старта, чтобы не мешать polling.
        await asyncio.sleep(60)
        while True:
            try:
                # Поднимаем покрытие: грузим до 600 лиг по 100 матчей.
                # По факту /Leagues возвращает ~600 — это все известные лиги.
                # Для лиг без последних матчей цикл просто пропустится.
                await _services.history_backfill.run_once(  # type: ignore[union-attr]
                    leagues_limit=600, per_league=100
                )
            except Exception as exc:
                logger.warning("history-backfill error: {}", exc)
            await asyncio.sleep(6 * 3600)

    async def _calibration_loop() -> None:
        # P0-2: раз в сутки переобучаем изотонические кривые по рынкам.
        await asyncio.sleep(300)
        while True:
            try:
                await _services.calibration.fit_all()  # type: ignore[union-attr]
            except Exception as exc:
                logger.warning("calibration fit error: {}", exc)
            await asyncio.sleep(24 * 3600)

    async def _cache_warmer_loop() -> None:
        # P0-10: раз в 10 мин прогреваем кэш для матчей ближайших 24 ч.
        await asyncio.sleep(30)
        while True:
            try:
                await _services.cache_warmer.warm_once()  # type: ignore[union-attr]
            except Exception as exc:
                logger.debug("cache-warmer error: {}", exc)
            await asyncio.sleep(10 * 60)

    async def _resolver_loop() -> None:
        # Каждые 10 мин резолвим pending PredictionOutcome → hit/miss + счёт.
        # Покрывает все лиги, не только те, что попали в history_backfill,
        # — гарантия, что история пользователя автообновляется без участия
        # человека (раньше было 30 мин, ловили жалобы «не учитывается»).
        await asyncio.sleep(90)
        while True:
            try:
                await _services.predictions_resolver.resolve_pending()  # type: ignore[union-attr]
            except Exception as exc:
                logger.warning("predictions-resolver error: {}", exc)
            await asyncio.sleep(10 * 60)

    async def _topmatches_precompute_loop() -> None:
        # P1-11: раз в 30 мин предрасчёт прогнозов для топ-50 матчей.
        await asyncio.sleep(120)
        while True:
            try:
                await _services.topmatches_precompute.precompute_once()  # type: ignore[union-attr]
            except Exception as exc:
                logger.debug("topmatches precompute error: {}", exc)
            await asyncio.sleep(30 * 60)

    async def _standings_sync_loop() -> None:
        # Раз в час обновляем турнирные таблицы (до 60 лиг за проход,
        # последовательно — критично, чтобы не блокировать SQLite на
        # долгих write-транзакциях, см. LeagueStandingsService).
        # Старт с 10-минутной задержки: сначала пользователь, потом фон.
        await asyncio.sleep(10 * 60)
        while True:
            try:
                await _services.league_standings.sync_all()  # type: ignore[union-attr]
            except Exception as exc:
                logger.debug("standings-sync error: {}", exc)
            await asyncio.sleep(60 * 60)

    async def _league_aggregates_loop() -> None:
        # P0-fix: пересчёт avg_total / btts_rate / over_25_rate по лигам
        # из MatchResult. Без этого все лиги в `LeagueAggregateService.get`
        # падают на дефолт 2.65 и в отчётах «средний тотал лиги» одно и
        # то же число для всех турниров. Считаем сразу при старте и
        # дальше раз в 6 часов.
        try:
            n = await _services.league_aggregates.recompute_all()  # type: ignore[union-attr]
            logger.info("LeagueAggregateService warm-up: {} лиг", n)
        except Exception as exc:
            logger.warning("LeagueAggregateService warm-up failed: {}", exc)
        while True:
            await asyncio.sleep(6 * 3600)
            try:
                n = await _services.league_aggregates.recompute_all()  # type: ignore[union-attr]
                logger.info("LeagueAggregateService periodic: {} лиг", n)
            except Exception as exc:
                logger.warning("LeagueAggregateService periodic failed: {}", exc)

    learning_task = asyncio.create_task(_self_learning_loop())
    backfill_task = asyncio.create_task(_history_backfill_loop())
    resolver_task = asyncio.create_task(_resolver_loop())
    calibration_task = asyncio.create_task(_calibration_loop())
    warmer_task = asyncio.create_task(_cache_warmer_loop())
    precompute_task = asyncio.create_task(_topmatches_precompute_loop())
    standings_task = asyncio.create_task(_standings_sync_loop())
    league_agg_task = asyncio.create_task(_league_aggregates_loop())
    # PickAdjustmentCache: фоновый refresh-loop читает таблицу
    # `pick_adjustments` (заполняется SecondaryPickCalibrator'ом
    # в self-learning loop) и обновляет in-memory словарь.
    if _services.pick_adjustments is not None:
        await _services.pick_adjustments.start()

    polling_task = asyncio.create_task(dispatcher.start_polling(bot, allowed_updates=dispatcher.resolve_used_update_types()))
    stop_task = asyncio.create_task(stop_event.wait())
    await asyncio.wait({polling_task, stop_task}, return_when=asyncio.FIRST_COMPLETED)
    expire_task.cancel()
    learning_task.cancel()
    backfill_task.cancel()
    resolver_task.cancel()
    calibration_task.cancel()
    warmer_task.cancel()
    precompute_task.cancel()
    standings_task.cancel()
    league_agg_task.cancel()
    if _services.pick_adjustments is not None:
        await _services.pick_adjustments.stop()

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
