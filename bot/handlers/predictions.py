"""Обработчики поиска матча и выдачи прогноза."""

from __future__ import annotations

from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from api.sstats_client import SStatsClient
from bot.formatters import format_prediction
from bot.keyboards import (
    countries_keyboard,
    main_menu_keyboard,
    prediction_actions_keyboard,
    teams_keyboard,
)
from bot.states import MatchSearchStates
from bot.texts import (
    NO_MATCH_FOUND,
    NO_QUOTA,
    NO_TEAMS_FOUND,
    PREDICTION_API_ERROR,
    PREDICTION_LOADING,
    QUERY_PARSE_FAIL,
    QUERY_TOO_SHORT,
    TOO_MANY_TEAMS,
)
from config import Settings
from core.value_calculator import ValueCalculator
from db.models import PredictionLog, User
from db.repositories.prediction_repo import PredictionLogRepository
from db.repositories.query_history_repo import QueryHistoryRepository
from db.repositories.user_repo import UserRepository
from services.countries import country_ru, format_country
from services.match_finder import MatchFinder
from services.odds_parser import OddsParser
from services.prediction_service import PredictionResult, PredictionService

router = Router(name="predictions")


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


@router.message(Command("match"))
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
    sstats: SStatsClient = message.bot["sstats"]  # type: ignore[index]
    finder = MatchFinder(sstats)

    home_results = await finder.search_teams(home_query, limit=25)
    away_results = await finder.search_teams(away_query, limit=25)

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
    )

    if len(home_results) > 25 and len(away_results) > 25:
        await message.answer(TOO_MANY_TEAMS)
        return

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
        reply_markup=teams_keyboard(home_results[:20], callback_prefix="home"),
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
    home_filtered = [t for t in home_results if (((t.get("country") or {}).get("name")) == country)]
    away_filtered = [t for t in away_results if (((t.get("country") or {}).get("name")) == country)]

    if len(home_filtered) == 1 and len(away_filtered) == 1 and callback.message:
        await _select_pair_and_predict(callback.message, state, home_filtered[0], away_filtered[0])
        await callback.answer()
        return

    await state.update_data(home_filtered=home_filtered, away_filtered=away_filtered)
    await state.set_state(MatchSearchStates.choosing_home_team)
    if callback.message:
        await callback.message.edit_text(
            f"Страна: {format_country(country)}. Кого взять *хозяевами*?",
            reply_markup=teams_keyboard(home_filtered[:20] or home_results[:20], callback_prefix="home"),
            parse_mode="Markdown",
        )
    await callback.answer()


@router.callback_query(MatchSearchStates.choosing_home_team, F.data.startswith("home:"))
async def home_picked(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.data:
        await callback.answer()
        return
    team_id = int(callback.data.split(":", 1)[1])
    data = await state.get_data()
    away_results = data.get("away_filtered") or data.get("away_results") or []
    await state.update_data(home_team_id=team_id)
    await state.set_state(MatchSearchStates.choosing_away_team)
    if callback.message:
        await callback.message.edit_text(
            "Кого взять *гостями*?",
            reply_markup=teams_keyboard(away_results[:20], callback_prefix="away"),
            parse_mode="Markdown",
        )
    await callback.answer()


@router.callback_query(MatchSearchStates.choosing_away_team, F.data.startswith("away:"))
async def away_picked(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.data or not callback.message:
        await callback.answer()
        return
    away_team_id = int(callback.data.split(":", 1)[1])
    data = await state.get_data()
    home_team_id = int(data.get("home_team_id") or 0)
    if home_team_id == 0:
        await callback.message.edit_text("Что-то пошло не так. Попробуй заново /match.")
        await callback.answer()
        return
    sstats: SStatsClient = callback.message.bot["sstats"]  # type: ignore[index]
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
    await _run_prediction(callback.message, state, cand.game_id)
    await callback.answer()


@router.callback_query(F.data.startswith("predict:refresh:"))
async def refresh_prediction(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.data or not callback.message:
        await callback.answer()
        return
    game_id = int(callback.data.rsplit(":", 1)[1])
    sstats: SStatsClient = callback.message.bot["sstats"]  # type: ignore[index]
    await sstats.cache.invalidate(prefix=f"odds:{game_id}")
    await sstats.cache.invalidate(prefix=f"glicko:{game_id}")
    await _run_prediction(callback.message, state, game_id, edit=True)
    await callback.answer("Обновлено")


@router.callback_query(F.data.startswith("predict:"))
async def predict_match_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.data or not callback.message:
        await callback.answer()
        return
    parts = callback.data.split(":")
    if len(parts) < 2:
        await callback.answer()
        return
    if parts[1] in {"refresh", "best", "all"}:
        return
    try:
        game_id = int(parts[1])
    except ValueError:
        await callback.answer("Неверный матч.")
        return
    await _run_prediction(callback.message, state, game_id, edit=True)
    await callback.answer()


async def _select_pair_and_predict(
    message: Message,
    state: FSMContext,
    home_team: dict[str, Any],
    away_team: dict[str, Any],
) -> None:
    sstats: SStatsClient = message.bot["sstats"]  # type: ignore[index]
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
) -> None:
    settings: Settings = message.bot["settings"]  # type: ignore[index]
    sstats: SStatsClient = message.bot["sstats"]  # type: ignore[index]
    session: AsyncSession = message.bot["session_factory"]()  # type: ignore[index]
    user: User | None = None

    try:
        if message.from_user is not None:
            user_repo = UserRepository(session)
            user = await user_repo.get_by_tg_id(message.from_user.id)

        if user is None:
            await message.answer("Сначала вызови /start.")
            await session.commit()
            return

        repo = UserRepository(session)
        consumed = await repo.consume_quota(
            user, daily_quota_for_subs=settings.top_predictions
        )
        if not consumed:
            await message.answer(
                NO_QUOTA.format(bonus=settings.referral_bonus_signup),
                parse_mode="Markdown",
                reply_markup=main_menu_keyboard(),
            )
            await session.commit()
            return

        loading_msg = None
        if not edit:
            loading_msg = await message.answer(PREDICTION_LOADING)

        value_calc = ValueCalculator(
            min_odds=settings.min_value_odds,
            min_value_percent=settings.min_value_percent,
        )
        service = PredictionService(
            sstats, value_calculator=value_calc, odds_parser=OddsParser()
        )
        try:
            result: PredictionResult | None = await service.predict(game_id)
        except Exception as exc:
            logger.exception("predict failed: {}", exc)
            if loading_msg:
                await loading_msg.delete()
            await message.answer(PREDICTION_API_ERROR)
            await session.commit()
            return

        if result is None:
            if loading_msg:
                await loading_msg.delete()
            await message.answer(PREDICTION_API_ERROR)
            await session.commit()
            return

        text = format_prediction(
            result,
            top_predictions=settings.top_predictions,
            top_value=settings.top_value_bets,
            free_left=user.free_predictions_left or 0,
            bonus_left=user.bonus_predictions or 0,
            tz_offset=settings.timezone_offset,
        )
        keyboard = prediction_actions_keyboard(result.game_id)

        if loading_msg:
            await loading_msg.delete()

        if edit:
            try:
                await message.edit_text(text, reply_markup=keyboard, parse_mode="Markdown")
            except Exception:
                await message.answer(text, reply_markup=keyboard, parse_mode="Markdown")
        else:
            await message.answer(text, reply_markup=keyboard, parse_mode="Markdown")

        log_repo = PredictionLogRepository(session)
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
            )
        )

        # Трекаем топ-3 валуйные ставки в in-memory аналитике,
        # чтобы /admin_analytics показывал hit-rate и ROI по реальным пикам
        try:
            analytics = message.bot["analytics"]  # type: ignore[index]
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
    except Exception:
        await session.rollback()
        raise
    finally:
        await state.clear()
        await session.close()


_ = country_ru  # keep imported for type hint reference
