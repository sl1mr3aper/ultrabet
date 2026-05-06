"""Обработчики поиска матча и выдачи прогноза."""

from __future__ import annotations

import json
from typing import Any

from aiogram import F, Router
from aiogram.filters import StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from api.sstats_client import SStatsClient
from bot.context import services
from bot.formatters import format_prediction
from bot.keyboards import (
    countries_keyboard,
    main_menu_keyboard,
    prediction_actions_keyboard,
    teams_keyboard,
)
from bot.progress import (
    minimal_loader,
    neural_loader,
    stage_for_elapsed,
)
from bot.states import MatchSearchStates
from bot.texts import (
    NO_MATCH_FOUND,
    NO_QUOTA,
    NO_TEAMS_FOUND,
    PREDICTION_API_ERROR,
    QUERY_PARSE_FAIL,
    QUERY_TOO_SHORT,
)
from config import Settings
from core.value_calculator import ValueCalculator
from db.models import PredictionLog, PredictionOutcome, User
from db.repositories.prediction_repo import PredictionLogRepository
from db.repositories.query_history_repo import QueryHistoryRepository
from db.repositories.user_repo import UserRepository
from services.countries import country_ru, format_country
from services.match_finder import MatchFinder
from services.odds_parser import OddsParser
from services.prediction_service import PredictionResult, PredictionService

router = Router(name="predictions")

TEAM_PAGE_SIZE = 10


def _parse_query(text: str) -> tuple[str, str] | None:
    if not text:
        return None
    for sep in (" - ", " — ", " – ", " vs ", " v ", " против ", "-"):
        if sep in text.lower() or sep in text:
            parts = text.split(sep, 1) if sep in text else text.lower().split(sep, 1)
            if len(parts) == 2:
                a, b = parts[0].strip(), parts[1].strip()
                if a and b:
                    return a, b
    return None


def _group_by_country(teams: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for t in teams:
        c = t.get("country") or {}
        cname = (c.get("name") if isinstance(c, dict) else c) or "—"
        out.setdefault(cname, []).append(t)
    return out
# [removed: command handler — UI is buttons-only]
async def match_command(
    message: Message,
    state: FSMContext,
) -> None:
    text = message.text or ""
    parts = text.split(" ", 1)
    if len(parts) < 2:
        await state.set_state(MatchSearchStates.waiting_for_query)
        await message.answer(
            "Пришли запрос в формате `Команда1 - Команда2`.", parse_mode="Markdown"
        )
        return
    await _process_query(message, state, parts[1])


@router.message(MatchSearchStates.waiting_for_query)
async def match_query(message: Message, state: FSMContext) -> None:
    await _process_query(message, state, message.text or "")


@router.message(StateFilter(None), F.text)
async def _smart_pair_fallback(message: Message, state: FSMContext) -> None:
    """Любая строка вида 'команда1 - команда2' / 'team1 vs team2' и т.п.
    в свободном вводе (БЕЗ активного FSM состояния) — сразу запускает
    поиск без нажатия кнопки. Хендлер не перехватывает ввод, когда
    пользователь уже внутри какого-то сценария (поиск лиги, фидбэк и т.п.).
    """
    text = (message.text or "").strip()
    if not text or text.startswith("/"):
        return
    if len(text) < 5:
        return
    if _parse_query(text) is None:
        return
    await _process_query(message, state, text)


async def _process_query(message: Message, state: FSMContext, raw_query: str) -> None:
    raw_query = (raw_query or "").strip()
    if len(raw_query) < 3:
        await message.answer(QUERY_TOO_SHORT)
        return

    pair = _parse_query(raw_query)
    if pair is None:
        await message.answer(QUERY_PARSE_FAIL, parse_mode="Markdown")
        return

    home_query, away_query = pair
    sstats: SStatsClient = services.sstats
    finder = MatchFinder(sstats)

    # Визуальный индикатор поиска: только бегущий таймер «прошло N сек.».
    # Раньше pct=0.45 показывался статично — на медленном поиске бар
    # «застревал» на 45 %. Теперь анимируем минималистично.
    import asyncio as _asyncio_search
    import time as _time_search

    _search_started = _time_search.monotonic()
    loader = await message.answer(
        minimal_loader("Ищу команды", elapsed_seconds=0),
        parse_mode="Markdown",
    )

    async def _animate_search() -> None:
        try:
            _last: str | None = None
            while True:
                await _asyncio_search.sleep(0.9)
                txt = minimal_loader(
                    "Ищу команды",
                    elapsed_seconds=_time_search.monotonic() - _search_started,
                )
                if txt != _last:
                    try:
                        await loader.edit_text(txt, parse_mode="Markdown")
                    except Exception:
                        pass
                    _last = txt
        except _asyncio_search.CancelledError:
            raise

    _search_animator = _asyncio_search.create_task(_animate_search())

    # Расширенный поиск (до 100 команд) — пагинируется по 10 на странице.
    try:
        home_results = await finder.search_teams(home_query, limit=100)
        away_results = await finder.search_teams(away_query, limit=100)
    finally:
        _search_animator.cancel()
        try:
            await _search_animator
        except (_asyncio_search.CancelledError, Exception):
            pass

    try:
        await loader.delete()
    except Exception:
        pass

    if not home_results:
        await message.answer(NO_TEAMS_FOUND.format(query=home_query))
        return
    if not away_results:
        await message.answer(NO_TEAMS_FOUND.format(query=away_query))
        return

    if len(home_results) == 1 and len(away_results) == 1:
        await _select_pair_and_predict(
            message, state,
            home_results[0], away_results[0],
        )
        return

    grouped_home = _group_by_country(home_results)
    grouped_away = _group_by_country(away_results)
    common_countries = sorted(set(grouped_home) & set(grouped_away))

    await state.update_data(
        home_query=home_query,
        away_query=away_query,
        home_results=home_results,
        away_results=away_results,
        home_page=0,
        away_page=0,
    )

    # Старая ветка «слишком много вариантов» больше не нужна — теперь
    # листаем 10/страницу до 100 команд.

    if common_countries:
        await state.set_state(MatchSearchStates.choosing_country)
        await message.answer(
            "Найдено несколько вариантов. Выбери страну/турнир:",
            reply_markup=countries_keyboard(common_countries[:30], callback_prefix="cnt"),
        )
        return

    await state.set_state(MatchSearchStates.choosing_home_team)
    await message.answer(
        "Кого взять *хозяевами*?",
        reply_markup=teams_keyboard(
            home_results[:TEAM_PAGE_SIZE],
            callback_prefix="home",
            page=0,
            page_size=TEAM_PAGE_SIZE,
            total=len(home_results),
        ),
        parse_mode="Markdown",
    )


@router.callback_query(MatchSearchStates.choosing_country, F.data.startswith("cnt:"))
async def country_picked(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.data:
        await callback.answer()
        return
    country = callback.data.split(":", 1)[1]
    data = await state.get_data()
    home_results = data.get("home_results") or []
    away_results = data.get("away_results") or []

    # «Любая страна» — для кросс-страновых матчей (Лига Чемпионов и т.п.).
    # Не фильтруем ни по одной стороне, чтобы пользователь мог собрать
    # пару из разных юрисдикций.
    if country == "__any__":
        home_filtered = list(home_results)
        away_filtered = list(away_results)
        header = "Все варианты. Кого взять *хозяевами*?"
    else:
        # Фильтруем только домашних: гостевая команда может быть из
        # другой страны (UCL/UEL и т.п.).
        home_filtered = [
            t for t in home_results
            if (((t.get("country") or {}).get("name")) == country)
        ]
        away_filtered = list(away_results)
        header = f"Страна хозяев: {format_country(country)}. Кого взять *хозяевами*?"

    if len(home_filtered) == 1 and len(away_filtered) == 1 and callback.message:
        await _select_pair_and_predict(callback.message, state, home_filtered[0], away_filtered[0])
        await callback.answer()
        return

    await state.update_data(
        home_filtered=home_filtered,
        away_filtered=away_filtered,
        home_page=0,
        away_page=0,
    )
    await state.set_state(MatchSearchStates.choosing_home_team)
    if callback.message:
        page_list = home_filtered or home_results
        await callback.message.edit_text(
            header,
            reply_markup=teams_keyboard(
                page_list[:TEAM_PAGE_SIZE],
                callback_prefix="home",
                page=0,
                page_size=TEAM_PAGE_SIZE,
                total=len(page_list),
            ),
            parse_mode="Markdown",
        )
    await callback.answer()


@router.callback_query(MatchSearchStates.choosing_home_team, F.data.startswith("home_p:"))
async def home_page_changed(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.data or not callback.message:
        await callback.answer()
        return
    try:
        page = max(0, int(callback.data.split(":", 1)[1]))
    except ValueError:
        await callback.answer()
        return
    data = await state.get_data()
    src = data.get("home_filtered") or data.get("home_results") or []
    start = page * TEAM_PAGE_SIZE
    page_slice = src[start:start + TEAM_PAGE_SIZE]
    await state.update_data(home_page=page)
    try:
        await callback.message.edit_reply_markup(
            reply_markup=teams_keyboard(
                page_slice,
                callback_prefix="home",
                page=page,
                page_size=TEAM_PAGE_SIZE,
                total=len(src),
            )
        )
    except Exception:
        pass
    await callback.answer()


@router.callback_query(MatchSearchStates.choosing_away_team, F.data.startswith("away_p:"))
async def away_page_changed(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.data or not callback.message:
        await callback.answer()
        return
    try:
        page = max(0, int(callback.data.split(":", 1)[1]))
    except ValueError:
        await callback.answer()
        return
    data = await state.get_data()
    src = data.get("away_filtered") or data.get("away_results") or []
    start = page * TEAM_PAGE_SIZE
    page_slice = src[start:start + TEAM_PAGE_SIZE]
    await state.update_data(away_page=page)
    try:
        await callback.message.edit_reply_markup(
            reply_markup=teams_keyboard(
                page_slice,
                callback_prefix="away",
                page=page,
                page_size=TEAM_PAGE_SIZE,
                total=len(src),
            )
        )
    except Exception:
        pass
    await callback.answer()


@router.callback_query(F.data == "noop")
async def _noop_cb(callback: CallbackQuery) -> None:
    await callback.answer()


@router.callback_query(MatchSearchStates.choosing_home_team, F.data.startswith("home:"))
async def home_picked(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.data:
        await callback.answer()
        return
    team_id = int(callback.data.split(":", 1)[1])
    data = await state.get_data()
    away_results = data.get("away_filtered") or data.get("away_results") or []
    await state.update_data(home_team_id=team_id, away_page=0)
    await state.set_state(MatchSearchStates.choosing_away_team)
    if callback.message:
        await callback.message.edit_text(
            "Кого взять *гостями*?",
            reply_markup=teams_keyboard(
                away_results[:TEAM_PAGE_SIZE],
                callback_prefix="away",
                page=0,
                page_size=TEAM_PAGE_SIZE,
                total=len(away_results),
            ),
            parse_mode="Markdown",
        )
    await callback.answer()


@router.callback_query(MatchSearchStates.choosing_away_team, F.data.startswith("away:"))
async def away_picked(callback: CallbackQuery, state: FSMContext) -> None:
    # Ack сразу, чтобы Telegram не пометил запрос как "query is too old"
    # пока строится прогноз (>15с лимит).
    try:
        await callback.answer()
    except Exception:
        pass
    if not callback.data or not callback.message:
        return
    away_team_id = int(callback.data.split(":", 1)[1])
    data = await state.get_data()
    home_team_id = int(data.get("home_team_id") or 0)
    if home_team_id == 0:
        await callback.message.edit_text("Что-то пошло не так. Попробуй заново /match.")
        await callback.answer()
        return
    sstats: SStatsClient = services.sstats
    finder = MatchFinder(sstats)
    cand = await finder.find_match_for_teams(home_team_id, away_team_id)
    if cand is None:
        team_home = await sstats.get_team(home_team_id)
        team_away = await sstats.get_team(away_team_id)
        names = (
            (team_home or {}).get("name") or "?",
            (team_away or {}).get("name") or "?",
        )
        await callback.message.edit_text(
            NO_MATCH_FOUND.format(home=names[0], away=names[1]),
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard(),
        )
        await callback.answer()
        return
    # edit=True, чтобы лоадер заменил собой клавиатуру выбора гостей
    # и не оставлял дублирующих сообщений в чате.
    await _run_prediction(
        callback.message, state, cand.game_id,
        edit=True, caller_tg_id=callback.from_user.id,
    )


@router.callback_query(F.data.startswith("predict:csv:"))
async def predict_csv(callback: CallbackQuery) -> None:
    """Отдать CSV с данными матча."""
    try:
        await callback.answer("Готовлю CSV…")
    except Exception:
        pass
    if not callback.data or not callback.message:
        return
    try:
        game_id = int(callback.data.rsplit(":", 1)[1])
    except ValueError:
        return
    # Прогресс-сообщение, чтобы пользователь не думал, что бот завис.
    progress: Message | None = None
    try:
        progress = await callback.message.answer(
            minimal_loader("CSV-данные матча", elapsed_seconds=0),
            parse_mode="Markdown",
        )
    except Exception:
        progress = None

    from services.csv_export import render_match_csv
    sstats: SStatsClient = services.sstats
    try:
        bundle = await sstats.get_full_match_data(game_id)
    except Exception as exc:
        logger.warning("CSV bundle fetch failed: {}", exc)
        if progress is not None:
            try:
                await progress.edit_text(
                    "Не удалось собрать CSV-данные. Попробуй позже."
                )
            except Exception:
                await callback.message.answer(
                    "Не удалось собрать CSV-данные. Попробуй позже."
                )
        else:
            await callback.message.answer(
                "Не удалось собрать CSV-данные. Попробуй позже."
            )
        return
    payload = render_match_csv(bundle)
    from aiogram.types import BufferedInputFile
    file_name = f"match_{game_id}_raw.csv"
    file = BufferedInputFile(payload, filename=file_name)
    await callback.message.answer_document(
        document=file,
        caption=(
            "📊 *CSV-данные матча* (матч, коэффициенты, травмы, "
            "последние игры, профитность, таблица сезона)"
        ),
        parse_mode="Markdown",
    )
    # Убираем «индикатор загрузки», файл уже отправлен отдельным сообщением.
    if progress is not None:
        try:
            await progress.delete()
        except Exception:
            pass


@router.callback_query(F.data.startswith("predict:refresh:"))
async def refresh_prediction(callback: CallbackQuery, state: FSMContext) -> None:
    # Ack сразу, чтобы Telegram не отдал "query is too old" пока строится прогноз
    try:
        await callback.answer("Обновляю…")
    except Exception:
        pass
    if not callback.data or not callback.message:
        return
    game_id = int(callback.data.rsplit(":", 1)[1])
    sstats: SStatsClient = services.sstats
    await sstats.cache.invalidate(prefix=f"odds:{game_id}")
    await sstats.cache.invalidate(prefix=f"glicko:{game_id}")
    await _run_prediction(
        callback.message, state, game_id,
        edit=True, caller_tg_id=callback.from_user.id,
    )


@router.callback_query(F.data.startswith("predict:"))
async def predict_match_cb(callback: CallbackQuery, state: FSMContext) -> None:
    # Ack сразу — если прогноз будет считаться >15с, Telegram уже не примет ответ
    try:
        await callback.answer()
    except Exception:
        pass
    if not callback.data or not callback.message:
        return
    parts = callback.data.split(":")
    if len(parts) < 2:
        return
    if parts[1] in {"refresh", "best", "all", "csv"}:
        return
    try:
        game_id = int(parts[1])
    except ValueError:
        return
    # Сохраняем «откуда пришли» в навигационный стек, чтобы кнопка
    # «Назад» внутри карточки прогноза возвращала в ту же подборку
    # (сегодня/завтра/live/лига/…), а не в главное меню.
    data = await state.get_data()
    origin = data.get("prediction_origin")
    if isinstance(origin, str) and origin:
        from bot.navigation import nav_push
        await nav_push(state, origin)
    await _run_prediction(
        callback.message, state, game_id,
        edit=True, caller_tg_id=callback.from_user.id,
    )


async def _select_pair_and_predict(
    message: Message,
    state: FSMContext,
    home_team: dict[str, Any],
    away_team: dict[str, Any],
) -> None:
    sstats: SStatsClient = services.sstats
    finder = MatchFinder(sstats)
    cand = await finder.find_match_for_teams(int(home_team.get("id")), int(away_team.get("id")))
    if cand is None:
        await message.answer(
            NO_MATCH_FOUND.format(home=home_team.get("name"), away=away_team.get("name")),
            parse_mode="Markdown",
            reply_markup=main_menu_keyboard(),
        )
        await state.clear()
        return
    await _run_prediction(message, state, cand.game_id)


async def _run_prediction(
    message: Message,
    state: FSMContext,
    game_id: int,
    *,
    edit: bool = False,
    caller_tg_id: int | None = None,
) -> None:
    settings: Settings = services.settings
    sstats: SStatsClient = services.sstats
    session: AsyncSession = services.session_factory()
    user: User | None = None

    try:
        tg_id = caller_tg_id
        if tg_id is None and message.from_user is not None:
            tg_id = message.from_user.id
        if tg_id is not None:
            user_repo = UserRepository(session)
            user = await user_repo.get_by_tg_id(tg_id)
            if user is None:
                # Пользователь кликает до /start — создадим его на лету
                user, _ = await user_repo.get_or_create(
                    tg_id=tg_id,
                    username=None,
                    first_name=None,
                    last_name=None,
                    language_code=None,
                    free_initial=settings.free_predictions_initial,
                )

        if user is None:
            await message.answer("Сначала вызови /start.")
            await session.commit()
            return

        repo = UserRepository(session)
        # Если подписка только что закончилась — показываем разовое
        # уведомление, прежде чем переходить на бесплатные отчёты.
        try:
            from datetime import UTC
            from datetime import datetime as _dt

            now_ = _dt.now(tz=UTC)
            su = user.subscription_until
            if su is not None and su.tzinfo is None:
                su = su.replace(tzinfo=UTC)
            notified = user.subscription_expired_notified_at
            if notified is not None and notified.tzinfo is None:
                notified = notified.replace(tzinfo=UTC)
            if (
                su is not None
                and su <= now_
                and (notified is None or notified < su)
            ):
                await message.answer(
                    "ℹ️ *Подписка закончилась.*\n"
                    "Дальше отчёты списываются с бесплатных. "
                    "Если они закончатся — обнови подписку.",
                    parse_mode="Markdown",
                )
                user.subscription_expired_notified_at = now_
                await session.flush()
        except Exception as _sub_exc:
            logger.debug("subscription expiry notice skipped: {}", _sub_exc)
        # Предпроверка: есть ли право на запрос. Не списываем — спишем
        # только после успешной генерации отчёта.
        allowed, _src = await repo.check_quota(
            user, subscription_daily_limit=settings.subscription_daily_limit,
        )
        if not allowed:
            await message.answer(
                NO_QUOTA.format(bonus=settings.referral_bonus_signup),
                parse_mode="Markdown",
                reply_markup=main_menu_keyboard(),
            )
            await session.commit()
            return

        import asyncio as _asyncio
        import time as _time

        # Показываем индикатор загрузки во всех сценариях — включая клики
        # по кнопкам матчей «Сегодня / Завтра» (edit=True). Если edit —
        # редактируем исходное сообщение, иначе шлём новое.
        loading_msg = None
        sent_new_loading = False
        _started = _time.monotonic()

        _pct0, _stage0 = stage_for_elapsed(0.0)
        initial_loader = neural_loader(
            "Готовлю прогноз",
            pct=_pct0,
            stage=_stage0,
            elapsed="0 сек",
        )
        if edit:
            try:
                await message.edit_text(initial_loader, parse_mode="Markdown")
                loading_msg = message
            except Exception:
                loading_msg = await message.answer(
                    initial_loader, parse_mode="Markdown",
                )
                sent_new_loading = True
        else:
            loading_msg = await message.answer(
                initial_loader, parse_mode="Markdown",
            )
            sent_new_loading = True

        async def _advance(text: str) -> None:
            if loading_msg is None:
                return
            try:
                await loading_msg.edit_text(text, parse_mode="Markdown")
            except Exception:
                pass

        value_calc = ValueCalculator(
            min_odds=settings.min_value_odds,
            min_value_percent=settings.min_value_percent,
            min_probability=settings.min_value_probability,
        )
        try:
            learner = services.self_learner
        except AttributeError:
            learner = None
        try:
            nb_bet = services.nb_bet_client
        except AttributeError:
            nb_bet = None
        service = PredictionService(
            sstats,
            value_calculator=value_calc,
            odds_parser=OddsParser(),
            self_learner=learner,
            nb_bet_client=nb_bet,
        )

        async def _animate() -> None:
            """Динамический прогресс-бар: полоса + стадия + таймер + ETA.

            Кадр обновляется каждые ~1.0 сек (Telegram rate-limit на edit
            одного сообщения ≈ 1/сек). Между стадиями процент
            интерполируется линейно, поэтому полоска плавно ползёт, а
            строка «идёт N сек.» обновляется каждую секунду.
            """
            try:
                _last_text: str | None = None
                while True:
                    await _asyncio.sleep(1.0)
                    elapsed = _time.monotonic() - _started
                    _pct, _stage = stage_for_elapsed(elapsed)
                    text = neural_loader(
                        "Готовлю прогноз",
                        pct=_pct,
                        stage=_stage,
                        elapsed=f"{int(elapsed)} сек",
                    )
                    if text != _last_text:
                        await _advance(text)
                        _last_text = text
            except _asyncio.CancelledError:
                raise

        # Фиксируем все ранние записи (создание пользователя, нотис о
        # подписке) и ОТПУСКАЕМ write-lock SQLite перед длинной чередой
        # SStats-вызовов. Иначе одна такая транзакция держит lock до
        # минуты и другие корутины валятся с «database is locked».
        try:
            await session.commit()
        except Exception as _cmt_exc:
            logger.debug("pre-predict commit skipped: {}", _cmt_exc)

        animator = _asyncio.create_task(_animate())
        # P1-11: сначала пробуем взять готовый прогноз из предрасчёта.
        try:
            _precomp = getattr(services, "topmatches_precompute", None)
        except Exception:
            _precomp = None
        _cached_result: PredictionResult | None = None
        if _precomp is not None:
            try:
                _cached_result = _precomp.get(int(game_id))
            except Exception:
                _cached_result = None
        # Если матч уже в прошлом — заранее записываем MatchResult с
        # итоговым счётом, чтобы PredictionService.predict() прочитал
        # is_finished/home_score/away_score и формат показал «✅ итог X:Y».
        try:
            _resolver = getattr(services, "predictions_resolver", None)
            if _resolver is not None:
                await _resolver.ensure_match_result(int(game_id))
        except Exception as _ensure_exc:
            logger.debug(
                "ensure_match_result({}) skipped: {}", game_id, _ensure_exc,
            )
        try:
            if _cached_result is not None:
                result: PredictionResult | None = _cached_result
            else:
                result = await service.predict(game_id)
        except Exception as exc:
            animator.cancel()
            logger.exception("predict failed: {}", exc)
            if loading_msg and sent_new_loading:
                try:
                    await loading_msg.delete()
                except Exception:
                    pass
            await message.answer(PREDICTION_API_ERROR)
            await session.commit()
            return
        finally:
            animator.cancel()

        if result is None:
            if loading_msg and sent_new_loading:
                try:
                    await loading_msg.delete()
                except Exception:
                    pass
            await message.answer(PREDICTION_API_ERROR)
            await session.commit()
            return

        # Отчёт получен — теперь списываем квоту
        await repo.commit_quota(
            user, subscription_daily_limit=settings.subscription_daily_limit,
        )

        # ── Probability Regulator: пересчёт топ-15 по истории ──
        # Бирём hit-rate каждого market_key по последним 200 матчам этой
        # лиги + кросс-лиговую обратную связь из prediction_outcomes.
        # Если данных мало — модуль вернёт почти исходные probs.
        try:
            from services.regulator_service import RegulatorService

            _reg_svc = RegulatorService(session)
            _reg = await _reg_svc.regulate(
                result.probabilities, league_id=result.league_id,
            )
            # Применяем скорректированные вероятности обратно
            new_probs = {k: v.p_corrected for k, v in _reg.items()}
            result.probabilities = new_probs
            # Лог для аудита
            _max_games = max(
                (v.hist_games for v in _reg.values()), default=0,
            )
            _max_delta = max(
                (abs(v.delta_pp) for v in _reg.values()), default=0.0,
            )
            logger.info(
                "regulator: league_id={} keys={} hist_max={} max_delta={:.2f}pp",
                result.league_id, len(_reg), _max_games, _max_delta,
            )
            result.regulated = {
                k: {
                    "p_model": v.p_model,
                    "p_corrected": v.p_corrected,
                    "hist_hits": v.hist_hits,
                    "hist_games": v.hist_games,
                    "delta_pp": v.delta_pp,
                }
                for k, v in _reg.items()
            }
        except Exception as _reg_exc:
            logger.warning("regulator skipped: {}", _reg_exc)

        text = format_prediction(
            result,
            top_predictions=settings.top_predictions,
            top_value=settings.top_value_bets,
            free_left=user.free_predictions_left or 0,
            bonus_left=0,
            tz_offset=settings.timezone_offset,
            daily_used=user.daily_used or 0,
            daily_quota=(
                min(user.subscription_daily_quota or 0, settings.subscription_daily_limit)
                if user.subscription_plan else 0
            ),
            is_admin=bool(user.is_admin),
        )

        # ── H2H блок (очные встречи, до 5 последних) ──────────
        # Используем /Games?team1Id=…&team2Id=… — бесплатный эндпоинт SStats.
        try:
            if result.home_team_id and result.away_team_id:
                from services.h2h_service import H2HService

                _h2h_service = H2HService(sstats, max_matches=5)
                _h2h = await _h2h_service.fetch(
                    result.home_team_id, result.away_team_id,
                )
                if _h2h.total_played:
                    _h2h_lines = [
                        "",
                        "🤝 *H2H* _(очные встречи)_",
                        (
                            f"• {result.home_name} "
                            f"побед: *{_h2h.home_wins}*  ·  "
                            f"ничьи: *{_h2h.draws}*  ·  "
                            f"{result.away_name} "
                            f"побед: *{_h2h.away_wins}*"
                        ),
                        (
                            f"• Ср. тотал: *{_h2h.avg_total_goals:.2f}*  ·  "
                            f"обе забили: *{_h2h.btts_pct:.0f}%*"
                        ),
                    ]
                    # Последние 3 матча с результатом
                    for m in _h2h.matches[:3]:
                        if m.home_score is None or m.away_score is None:
                            continue
                        _d = (m.date_iso or "")[:10]
                        _h_name = (m.home_name or "?").replace("*", "").replace("_", " ")
                        _a_name = (m.away_name or "?").replace("*", "").replace("_", " ")
                        _h2h_lines.append(
                            f"  · {_d} {_h_name} {m.home_score}:"
                            f"{m.away_score} {_a_name}"
                        )
                    text += "\n" + "\n".join(_h2h_lines)
        except Exception as _h2h_exc:
            logger.debug("h2h block skipped: {}", _h2h_exc)

        # ── Sharp-money баннер отключён: он раскрывает числовые кфы,
        # что противоречит текущей политике отчёта (показываем только
        # вероятности и честный КФ = 1/p).

        # Опциональное AI-уточнение топ-1 главного прогноза.
        # Не валит отчёт, если модель медленная или не отдала ответ.
        try:
            ai_refiner = services.ai_refiner
        except AttributeError:
            ai_refiner = None
        if ai_refiner is not None:
            try:
                raw_bundle = await sstats.get_full_match_data(result.game_id)
            except Exception:
                raw_bundle = None
            ai_text = await ai_refiner.refine(result, raw_bundle)
            if ai_text:
                # Telegram parse_mode=Markdown ломается на несбалансированных
                # символах форматирования — снимаем их с AI-ответа целиком.
                _safe = (
                    ai_text.replace("*", "")
                    .replace("_", "")
                    .replace("`", "")
                    .replace("[", "(")
                    .replace("]", ")")
                )
                ai_block = (
                    f"\n🤖 *Вердикт ИИ по главному прогнозу*\n{_safe}"
                )
                # Блок «осталось прогнозов» должен быть последним. Пробуем
                # вставить AI-вердикт прямо перед ним; если не нашли —
                # просто аппендим.
                quota_markers = (
                    "🆓 Бесплатных запросов осталось:",
                    "💎 Квота подписки:",
                    "👑 *Admin-режим:*",
                )
                inserted = False
                for marker in quota_markers:
                    pos = text.rfind(marker)
                    if pos >= 0:
                        head, tail = text[:pos], text[pos:]
                        text = head.rstrip() + "\n" + ai_block + "\n\n" + tail
                        inserted = True
                        break
                if not inserted:
                    text += "\n" + ai_block

        keyboard = prediction_actions_keyboard(result.game_id)

        # Telegram ограничивает сообщение 4096 символами. Если переборщили
        # (длинный summary + profits + AI), аккуратно обрежем перед отправкой.
        TG_LIMIT = 4000
        if len(text) > TG_LIMIT:
            cut = text[:TG_LIMIT]
            # обрезать по последнему переводу строки, чтобы не оборвать markdown
            nl = cut.rfind("\n")
            if nl > 3000:
                cut = cut[:nl]
            text = cut + "\n\n…(отчёт обрезан, полные данные в CSV-кнопке)"

        # На случай если в готовом тексте окажется битый markdown
        # (Telegram парсер падает на несбалансированных `*`/`_`/`[`),
        # пробуем сначала с Markdown, потом без него — лишь бы доставить отчёт.
        async def _send_with_fallback(action, *, target):  # type: ignore[no-untyped-def]
            try:
                await action(text, reply_markup=keyboard, parse_mode="Markdown")
                return True
            except Exception as exc:
                logger.warning(
                    "deliver md failed for game={} ({}): {}",
                    result.game_id, target, exc,
                )
            try:
                await action(text, reply_markup=keyboard)
                return True
            except Exception as exc2:
                logger.warning(
                    "deliver plain failed for game={} ({}): {}",
                    result.game_id, target, exc2,
                )
                return False

        delivered = False
        if loading_msg is not None and not sent_new_loading:
            delivered = await _send_with_fallback(
                loading_msg.edit_text, target="loader-edit",
            )
        if not delivered and sent_new_loading and loading_msg is not None:
            try:
                await loading_msg.delete()
            except Exception:
                pass
        if not delivered:
            if edit:
                delivered = await _send_with_fallback(
                    message.edit_text, target="message-edit",
                )
            if not delivered:
                await _send_with_fallback(
                    message.answer, target="message-answer",
                )

        log_repo = PredictionLogRepository(session)
        # Сохраняем топ-1 главный прогноз в payload, чтобы /history показал детали
        # и сматчить с PredictionOutcome (hit/miss) по market_key.
        _payload_json: str | None = None
        try:
            from bot.formatters import _pick_top_one
            from core.markets import label_for as _label_for_hist

            _top = _pick_top_one(result)
            if _top is not None:
                _k, _p, _o, _b = _top
                try:
                    _lbl = _label_for_hist(
                        _k, home=result.home_name, away=result.away_name,
                    )
                except Exception:
                    _lbl = _k
                _payload_json = json.dumps(
                    {
                        "top_market_key": _k,
                        "top_label": _lbl,
                        "top_prob": _p,
                        "top_odd": _o,
                        "top_book": _b,
                    },
                    ensure_ascii=False,
                )
        except Exception:
            _payload_json = None
        await log_repo.add(
            PredictionLog(
                user_id=user.id,
                game_id=result.game_id,
                home_name=result.home_name,
                away_name=result.away_name,
                league_name=result.league_name,
                home_xg=result.home_xg,
                away_xg=result.away_xg,
                home_rating=result.home_rating,
                away_rating=result.away_rating,
                payload=_payload_json,
            )
        )

        # Трекаем топ-3 EV-ставки в in-memory аналитике,
        # чтобы /admin_analytics показывал hit-rate и ROI по реальным пикам
        try:
            analytics = services.analytics
        except KeyError:
            analytics = None
        if analytics is not None:
            for bet in sorted(
                result.value_bets[:3],
                key=lambda b: b.value_percent,
                reverse=True,
            ):
                try:
                    analytics.record_prediction(result, bet)
                except Exception as exc:
                    logger.debug("analytics record error: {}", exc)

        # Feedback-loop для self-learning: сохраняем топ-10 прогнозов
        # + рынок главного прогноза (если он не попал в топ-10 по вероятности,
        # иначе /history никогда не увидит для него hit/miss) + все
        # value-беты. Для одной пары (game_id, market_key) держим одну
        # запись — при повторном расчёте обновляем вероятность/кф.
        try:
            from sqlalchemy import select as _select

            odds_by_key: dict[str, float | None] = {
                vb.market_key: vb.actual_odds for vb in result.value_bets
            }
            sorted_top = sorted(
                result.probabilities.items(), key=lambda kv: kv[1], reverse=True,
            )[:10]
            to_save: dict[str, float] = {}
            for _k, _prob in sorted_top:
                to_save[str(_k)] = float(_prob)
            # Главный прогноз (EV-бест), чтобы /history проставил hit/miss.
            if _payload_json:
                try:
                    _payload_dict = json.loads(_payload_json)
                    _top_k = _payload_dict.get("top_market_key")
                    if isinstance(_top_k, str) and _top_k:
                        _top_prob = result.probabilities.get(_top_k)
                        if _top_prob is None and _payload_dict.get("top_prob"):
                            _top_prob = float(_payload_dict["top_prob"])
                        if _top_prob is not None:
                            to_save[_top_k] = float(_top_prob)
                except Exception:
                    pass
            # Все value-беты — полезный фидбек для калибровки кфов.
            for vb in result.value_bets:
                _vk = getattr(vb, "market_key", None)
                _vp = getattr(vb, "probability", None)
                if isinstance(_vk, str) and _vk and _vp is not None:
                    to_save.setdefault(_vk, float(_vp))

            if to_save:
                existing = set(
                    (
                        await session.scalars(
                            _select(PredictionOutcome.market_key).where(
                                PredictionOutcome.game_id == result.game_id,
                                PredictionOutcome.market_key.in_(list(to_save.keys())),
                            )
                        )
                    ).all()
                )
                for _mk, _pb in to_save.items():
                    if _mk in existing:
                        continue
                    session.add(
                        PredictionOutcome(
                            game_id=result.game_id,
                            market_key=_mk,
                            predicted_probability=_pb,
                            actual_odds=odds_by_key.get(_mk),
                        )
                    )
        except Exception as exc:
            logger.debug("prediction outcome record error: {}", exc)

        # Полная история ВСЕХ пиков по матчу (для secondary_pick_calibrator).
        # Отделено от PredictionOutcome потому что там хранится только
        # main+value, а тут — все 40+ рынков для условной калибровки.
        try:
            from services.match_pick_history import (
                PickSnapshot,
                record_picks,
            )

            _main_key: str | None = None
            if _payload_json:
                try:
                    _main_key = json.loads(_payload_json).get("top_market_key")
                except Exception:
                    _main_key = None
            # Берём сырые (model) вероятности из extra если есть, чтобы
            # SecondaryPickCalibrator работал на чистых данных без
            # обратной связи через ранее применённый adjustment_factor.
            _src_probs = (
                getattr(result, "extra", None) or {}
            ).get("probabilities_raw") or result.probabilities
            _all_picks = [
                PickSnapshot(
                    market_key=str(k),
                    probability=float(p),
                    fair_odds=(1.0 / p) if p > 1e-6 else None,
                )
                for k, p in _src_probs.items()
                if isinstance(k, str) and 0.0 < float(p) <= 1.0
            ]
            await record_picks(
                session,
                game_id=result.game_id,
                league_id=result.league_id,
                picks=_all_picks,
                main_pick_key=_main_key if isinstance(_main_key, str) else None,
                is_backtest=False,
                home_score=result.home_score,
                away_score=result.away_score,
            )
        except Exception as exc:
            logger.debug("match_pick_history record error: {}", exc)

        history = QueryHistoryRepository(session)
        await history.add(
            user_id=user.id,
            query_text=f"{result.home_name} - {result.away_name}",
            matched_game_id=result.game_id,
            success=True,
        )

        await session.commit()
        country_label = format_country(result.country_raw)
        logger.info(
            "prediction sent user={} game={} ({} vs {}) [{}]",
            user.tg_id, result.game_id, result.home_name, result.away_name, country_label,
        )

        # Если матч уже сыгран — резолвим созданные PredictionOutcome сразу,
        # чтобы пользователь в истории увидел ✅/❌ и счёт немедленно,
        # а не ждал следующего прохода фонового резолвера.
        try:
            from datetime import UTC as _UTC
            from datetime import datetime as _dt

            date_iso = getattr(result, "date_iso", "") or ""
            match_dt: _dt | None = None
            if date_iso:
                try:
                    match_dt = _dt.fromisoformat(
                        date_iso.replace("Z", "+00:00"),
                    )
                    if match_dt.tzinfo is None:
                        match_dt = match_dt.replace(tzinfo=_UTC)
                except ValueError:
                    match_dt = None
            resolver = getattr(services, "predictions_resolver", None)
            if (
                resolver is not None
                and match_dt is not None
                and match_dt < _dt.now(tz=_UTC)
            ):
                try:
                    await resolver.resolve_game(int(result.game_id))
                except Exception as _rx_exc:
                    logger.debug(
                        "inline resolve_game({}) failed: {}",
                        result.game_id, _rx_exc,
                    )
        except Exception as _exc:
            logger.debug("inline resolve setup error: {}", _exc)
    except Exception:
        await session.rollback()
        raise
    finally:
        # Не очищаем весь FSM-контекст: стек навигации и «откуда пришли»
        # должны пережить расчёт прогноза, иначе кнопка «Назад» на карточке
        # прогноза не знает, куда возвращаться.
        _data = await state.get_data()
        _nav_stack = _data.get("_nav_stack")
        _origin = _data.get("prediction_origin")
        await state.clear()
        _preserved: dict[str, Any] = {}
        if _nav_stack is not None:
            _preserved["_nav_stack"] = _nav_stack
        if _origin is not None:
            _preserved["prediction_origin"] = _origin
        if _preserved:
            await state.update_data(**_preserved)
        await session.close()


_ = country_ru  # keep imported for type hint reference
