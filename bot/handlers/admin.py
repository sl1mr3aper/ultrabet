"""Админ-панель."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta, timezone

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder
from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from bot.context import services
from bot.keyboards import home_keyboard
from bot.states import AdminStates
from bot.texts import (
    ADMIN_BACKTEST_ASK_DATE,
    ADMIN_BACKTEST_LOADING,
    ADMIN_NOT_ALLOWED,
    ADMIN_PANEL,
    ADMIN_PREDICTION_ANALYSIS_ASK_DATE,
    ADMIN_PREDICTION_ANALYSIS_INTRO,
    ADMIN_PREDICTION_ANALYSIS_LOADING,
    ADMIN_PREDICTION_ANALYSIS_NO_MATCHES,
    Buttons,
)
from config import Settings
from core.value_engine import select_best_pick
from db.models import User
from db.repositories.user_repo import UserRepository
from services.referral_service import ReferralService
from services.subscription_service import SUBSCRIPTION_PLANS, SubscriptionService

router = Router(name="admin")

MSK = timezone(timedelta(hours=3))


def _is_admin(user: User | None, settings: Settings) -> bool:
    if user is None:
        return False
    if user.is_admin:
        return True
    return user.tg_id in (settings.admin_ids or [])


@router.message(Command("admin"))
async def admin_panel(
    message: Message, user: User, session: AsyncSession, settings: Settings
) -> None:
    if not _is_admin(user, settings):
        await message.answer(ADMIN_NOT_ALLOWED)
        return
    repo = UserRepository(session)
    stats = await repo.stats()
    text = ADMIN_PANEL.format(
        total=stats["total"],
        subs=stats["active_subscriptions"],
        blocked=stats["blocked"],
        new=stats["new_24h"],
    )
    await message.answer(text, parse_mode="Markdown", reply_markup=home_keyboard(message.from_user.id if message.from_user else None))


@router.message(Command("grant"))
async def grant_subscription(
    message: Message, user: User, session: AsyncSession, settings: Settings
) -> None:
    if not _is_admin(user, settings):
        await message.answer(ADMIN_NOT_ALLOWED)
        return
    parts = (message.text or "").split()
    if len(parts) != 3:
        await message.answer("Использование: /grant <tg_id> <plan_code>")
        return
    try:
        target_tg_id = int(parts[1])
    except ValueError:
        await message.answer("tg_id должен быть числом.")
        return
    plan_code = parts[2]
    if plan_code not in SUBSCRIPTION_PLANS:
        await message.answer(f"Неизвестный тариф {plan_code}. Доступные: "
                              + ", ".join(SUBSCRIPTION_PLANS))
        return
    repo = UserRepository(session)
    target = await repo.get_by_tg_id(target_tg_id)
    if target is None:
        await message.answer("Пользователь не найден.")
        return
    sub = SubscriptionService(session)
    plan = await sub.activate(target, plan_code)
    if plan is None:
        await message.answer("Не удалось активировать.")
        return
    if target.referred_by_id:
        ref = ReferralService(
            session,
            bonus_signup=settings.referral_bonus_signup,
        )
        await ref.reward_for_subscription(referred=target, plan_code=plan_code)
    await session.flush()
    await message.answer(
        f"✅ Подписка *{plan.title}* активирована для tg_id={target_tg_id}",
        parse_mode="Markdown",
    )
    try:
        await message.bot.send_message(
            target_tg_id,
            f"🎉 Тебе подключена подписка *{plan.title}*. Дневная квота — *{plan.daily_quota}*.",
            parse_mode="Markdown",
        )
    except Exception as exc:
        logger.debug("can't notify {}: {}", target_tg_id, exc)


@router.message(Command("ban"))
async def ban_user(
    message: Message, user: User, session: AsyncSession, settings: Settings
) -> None:
    if not _is_admin(user, settings):
        return
    parts = (message.text or "").split()
    if len(parts) != 2:
        return
    try:
        tg_id = int(parts[1])
    except ValueError:
        return
    repo = UserRepository(session)
    target = await repo.get_by_tg_id(tg_id)
    if target:
        await repo.set_blocked(target, True)
        await message.answer(f"Заблокирован {tg_id}")


@router.message(Command("unban"))
async def unban_user(
    message: Message, user: User, session: AsyncSession, settings: Settings
) -> None:
    if not _is_admin(user, settings):
        return
    parts = (message.text or "").split()
    if len(parts) != 2:
        return
    try:
        tg_id = int(parts[1])
    except ValueError:
        return
    repo = UserRepository(session)
    target = await repo.get_by_tg_id(tg_id)
    if target:
        await repo.set_blocked(target, False)
        await message.answer(f"Разблокирован {tg_id}")


@router.message(Command("broadcast"), F.from_user)
async def broadcast(
    message: Message, user: User, session: AsyncSession, settings: Settings
) -> None:
    if not _is_admin(user, settings):
        return
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: /broadcast Текст рассылки")
        return
    text = parts[1]
    repo = UserRepository(session)
    users = await repo.all_users(limit=10000)
    sent = 0
    failed = 0
    for u in users:
        try:
            await message.bot.send_message(u.tg_id, text)
            sent += 1
        except Exception:
            failed += 1
    await message.answer(f"📨 Отправлено: {sent}, ошибок: {failed}")


@router.message(Command("admin_analytics"))
async def admin_analytics(
    message: Message, user: User, session: AsyncSession, settings: Settings
) -> None:
    """Показывает агрегированные метрики точности по прогнозам и ROI."""
    if not _is_admin(user, settings):
        await message.answer(ADMIN_NOT_ALLOWED)
        return
    try:
        analytics = services.analytics
    except KeyError:
        analytics = None
    if analytics is None:
        await message.answer("Сервис аналитики не подключен.")
        return
    s = analytics.summary()
    lines = [
        "📊 *Аналитика прогнозов*",
        "",
        f"• Прогнозов всего: *{s.total_predictions}*",
        f"• Рассчитано: *{s.settled}*",
        f"• Выиграно: *{s.won}*",
        f"• Проиграно: *{s.lost}*",
        f"• Hit-rate: *{s.hit_rate_pct:.2f}%*",
        f"• ROI: *{s.roi_pct:+.2f}%*",
        f"• Средняя валуйность: *{s.avg_value_pct:.2f}%*",
        f"• Средний коэф: *{s.avg_odds:.2f}*",
        f"• Лучший стрик: *{s.best_streak}*",
        f"• Худший стрик: *{s.worst_streak}*",
    ]
    if s.markets_breakdown:
        lines.append("")
        lines.append("*Топ-рынки:*")
        for key, cnt in sorted(
            s.markets_breakdown.items(), key=lambda kv: kv[1], reverse=True
        )[:10]:
            lines.append(f"  • `{key}` → {cnt}")
    await message.answer(
        "\n".join(lines),
        parse_mode="Markdown",
        reply_markup=home_keyboard(
            message.from_user.id if message.from_user else None
        ),
    )


# ── Бэктест: анализ прогнозов по дате ────────────────────────


def _backtest_date_keyboard():
    """Клавиатура с кнопками «Сегодня», «Завтра» и «Отмена»."""
    builder = InlineKeyboardBuilder()
    builder.button(text=Buttons.ADMIN_BACKTEST_TODAY, callback_data="admin:backtest_today")
    builder.button(text="📅 Завтра (МСК)", callback_data="admin:backtest_tomorrow")
    builder.button(text=Buttons.CANCEL, callback_data="cancel")
    builder.adjust(2, 1)
    return builder.as_markup()


@router.callback_query(F.data.in_({"admin:backtest", "admin:mass_analysis"}))
async def admin_backtest_start(
    callback: CallbackQuery, user: User, settings: Settings, state: FSMContext,
) -> None:
    if not _is_admin(user, settings):
        await callback.answer(ADMIN_NOT_ALLOWED, show_alert=True)
        return
    await state.set_state(AdminStates.waiting_for_backtest_date)
    if callback.message:
        await callback.message.edit_text(
            ADMIN_BACKTEST_ASK_DATE,
            parse_mode="Markdown",
            reply_markup=_backtest_date_keyboard(),
        )
    await callback.answer()


# ── Анализ прогнозов: выбор количества матчей ────────────────


def _prediction_date_keyboard():
    """Шаг 1: выбор даты (сегодня / вчера / завтра / ввод)."""
    builder = InlineKeyboardBuilder()
    builder.button(text="📅 Сегодня", callback_data="admin:pa:date:today")
    builder.button(text="⏪ Вчера", callback_data="admin:pa:date:yesterday")
    builder.button(text="⏩ Завтра", callback_data="admin:pa:date:tomorrow")
    builder.button(text=Buttons.CANCEL, callback_data="cancel")
    builder.adjust(3, 1)
    return builder.as_markup()


def _prediction_count_keyboard():
    """Шаг 2: пресеты кол-ва матчей и отмена."""
    builder = InlineKeyboardBuilder()
    for n in (10, 20, 50, 100):
        builder.button(text=f"{n}", callback_data=f"admin:pa:n:{n}")
    builder.button(text=Buttons.CANCEL, callback_data="cancel")
    builder.adjust(4, 1)
    return builder.as_markup()


def _prediction_stop_keyboard():
    """Клавиатура с одной кнопкой «🛑 Остановить» во время выполнения."""
    builder = InlineKeyboardBuilder()
    builder.button(text=Buttons.ADMIN_STOP, callback_data="admin:pa:stop")
    builder.adjust(1)
    return builder.as_markup()


# Глобальный реестр активных задач анализа: tg_id -> asyncio.Task.
# Это позволяет кнопке «🛑 Остановить» отменить нужную задачу.
_PA_TASKS: dict[int, asyncio.Task] = {}


@router.callback_query(F.data == "admin:prediction_analysis")
async def admin_prediction_analysis_start(
    callback: CallbackQuery, user: User, settings: Settings, state: FSMContext,
) -> None:
    """Шаг 1: спрашиваем дату."""
    if not _is_admin(user, settings):
        await callback.answer(ADMIN_NOT_ALLOWED, show_alert=True)
        return
    await state.set_state(AdminStates.waiting_for_prediction_date)
    if callback.message:
        await callback.message.edit_text(
            ADMIN_PREDICTION_ANALYSIS_ASK_DATE,
            parse_mode="Markdown",
            reply_markup=_prediction_date_keyboard(),
        )
    await callback.answer()


async def _go_to_count_step(
    callback: CallbackQuery | Message,
    date_str: str,
    state: FSMContext,
) -> None:
    """Переход на шаг 2 (выбор кол-ва) после выбора даты."""
    await state.update_data(pa_date=date_str)
    await state.set_state(AdminStates.waiting_for_prediction_count)
    text = ADMIN_PREDICTION_ANALYSIS_INTRO.format(date=date_str)
    if isinstance(callback, CallbackQuery) and callback.message:
        await callback.message.edit_text(
            text, parse_mode="Markdown",
            reply_markup=_prediction_count_keyboard(),
        )
    else:
        await callback.answer(
            text, parse_mode="Markdown",
            reply_markup=_prediction_count_keyboard(),
        )


@router.callback_query(F.data.startswith("admin:pa:date:"))
async def admin_prediction_analysis_pick_date(
    callback: CallbackQuery, user: User, settings: Settings, state: FSMContext,
) -> None:
    if not _is_admin(user, settings):
        await callback.answer(ADMIN_NOT_ALLOWED, show_alert=True)
        return
    kind = (callback.data or "").rsplit(":", 1)[-1]
    now = datetime.now(MSK)
    if kind == "today":
        date_str = now.strftime("%Y-%m-%d")
    elif kind == "yesterday":
        date_str = (now - timedelta(days=1)).strftime("%Y-%m-%d")
    elif kind == "tomorrow":
        date_str = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    else:
        await callback.answer()
        return
    await callback.answer()
    await _go_to_count_step(callback, date_str, state)


@router.message(AdminStates.waiting_for_prediction_date, F.text)
async def admin_prediction_analysis_date_input(
    message: Message, user: User, settings: Settings, state: FSMContext,
) -> None:
    if not _is_admin(user, settings):
        await message.answer(ADMIN_NOT_ALLOWED)
        return
    text = (message.text or "").strip()
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        await message.answer(
            "❌ Неверный формат. Введи дату как ГГГГ-ММ-ДД (например 2026-04-30).",
        )
        return
    now_msk = datetime.now(MSK).replace(tzinfo=None)
    if parsed.date() < (now_msk.date() - timedelta(days=14)):
        await message.answer("❌ Максимум две недели назад.")
        return
    if parsed.date() > (now_msk.date() + timedelta(days=2)):
        await message.answer("❌ Максимум послезавтра.")
        return
    await _go_to_count_step(message, text, state)


@router.callback_query(F.data.startswith("admin:pa:n:"))
async def admin_prediction_analysis_pick_count(
    callback: CallbackQuery, user: User, settings: Settings, state: FSMContext,
) -> None:
    if not _is_admin(user, settings):
        await callback.answer(ADMIN_NOT_ALLOWED, show_alert=True)
        return
    payload = (callback.data or "").rsplit(":", 1)[-1]
    try:
        count = max(1, min(200, int(payload)))
    except ValueError:
        await callback.answer("Не понял число", show_alert=True)
        return
    data = await state.get_data()
    date_str = (data or {}).get("pa_date") or datetime.now(MSK).strftime("%Y-%m-%d")
    await callback.answer()
    await _run_prediction_analysis(callback, count, settings, state, date_str)


@router.callback_query(F.data == "admin:pa:stop")
async def admin_prediction_analysis_stop(
    callback: CallbackQuery, user: User, settings: Settings,
) -> None:
    if not _is_admin(user, settings):
        await callback.answer(ADMIN_NOT_ALLOWED, show_alert=True)
        return
    tg_id = callback.from_user.id if callback.from_user else None
    if tg_id is None:
        await callback.answer()
        return
    task = _PA_TASKS.get(int(tg_id))
    if task is not None and not task.done():
        task.cancel()
        await callback.answer("Останавливаю…", show_alert=False)
    else:
        await callback.answer("Нет активного анализа", show_alert=False)


@router.message(AdminStates.waiting_for_prediction_count, F.text)
async def admin_prediction_analysis_count_input(
    message: Message, user: User, settings: Settings, state: FSMContext,
) -> None:
    if not _is_admin(user, settings):
        await message.answer(ADMIN_NOT_ALLOWED)
        return
    text = (message.text or "").strip()
    try:
        count = int(text)
    except ValueError:
        await message.answer(
            "❌ Введи число от 1 до 200 (например 25), или нажми кнопку выше.",
        )
        return
    if count < 1 or count > 200:
        await message.answer("❌ Кол-во матчей должно быть в диапазоне 1–200.")
        return
    data = await state.get_data()
    date_str = (data or {}).get("pa_date") or datetime.now(MSK).strftime("%Y-%m-%d")
    await state.clear()
    await _run_prediction_analysis(message, count, settings, state, date_str)


@router.callback_query(F.data == "admin:backtest_today")
async def admin_backtest_today(
    callback: CallbackQuery, user: User, settings: Settings, state: FSMContext,
) -> None:
    if not _is_admin(user, settings):
        await callback.answer(ADMIN_NOT_ALLOWED, show_alert=True)
        return
    today = datetime.now(MSK).strftime("%Y-%m-%d")
    await callback.answer()
    await _run_backtest(callback, today, settings, state)


@router.callback_query(F.data == "admin:backtest_tomorrow")
async def admin_backtest_tomorrow(
    callback: CallbackQuery, user: User, settings: Settings, state: FSMContext,
) -> None:
    if not _is_admin(user, settings):
        await callback.answer(ADMIN_NOT_ALLOWED, show_alert=True)
        return
    tomorrow = (datetime.now(MSK) + timedelta(days=1)).strftime("%Y-%m-%d")
    await callback.answer()
    await _run_backtest(callback, tomorrow, settings, state)


@router.message(AdminStates.waiting_for_backtest_date, F.text)
async def admin_backtest_date_input(
    message: Message, user: User, settings: Settings, state: FSMContext,
) -> None:
    if not _is_admin(user, settings):
        await message.answer(ADMIN_NOT_ALLOWED)
        return
    text = (message.text or "").strip()
    try:
        parsed = datetime.strptime(text, "%Y-%m-%d")
    except ValueError:
        await message.answer(
            "❌ Неверный формат. Введи дату как ГГГГ-ММ-ДД (например 2026-04-29).",
        )
        return
    now_msk = datetime.now(MSK).replace(tzinfo=None)
    week_ago = now_msk - timedelta(days=7)
    if parsed.date() < week_ago.date():
        await message.answer("❌ Максимум неделя назад.")
        return
    tomorrow = now_msk.date() + timedelta(days=1)
    if parsed.date() > tomorrow:
        await message.answer("❌ Максимум завтра.")
        return
    await state.clear()
    await _run_backtest(message, text, settings, state)


async def _run_backtest(
    target: CallbackQuery | Message,
    date_str: str,
    settings: Settings,
    state: FSMContext,
) -> None:
    """Загрузить матчи на дату, прогнозировать, сравнить с реальностью."""
    import time as _time

    from aiogram.types import BufferedInputFile

    from core.value_calculator import ValueCalculator
    from db.models import BacktestResult
    from services.odds_parser import OddsParser
    from services.prediction_service import PredictionService

    sstats = services.sstats
    if sstats is None:
        _text = "❌ Сервис SStats не подключён."
        if isinstance(target, CallbackQuery) and target.message:
            await target.message.edit_text(_text)
        else:
            await target.answer(_text)
        return

    t0 = _time.monotonic()

    # Определяем chat для отправки файла
    if isinstance(target, CallbackQuery):
        chat = target.message
    else:
        chat = target

    # Сообщение «загружаю»
    loading_text = ADMIN_BACKTEST_LOADING.format(date=date_str)
    if isinstance(target, CallbackQuery) and target.message:
        msg = await target.message.edit_text(loading_text, parse_mode="Markdown")
    else:
        msg = await target.answer(loading_text, parse_mode="Markdown")

    # Загрузка всех матчей на дату (не фильтруем по статусу!)
    try:
        games = await sstats.list_games(date=date_str, limit=1000, cache_ttl=120)
    except Exception as exc:
        logger.error("backtest list_games error: {}", exc)
        if msg:
            await msg.edit_text(f"❌ Ошибка загрузки матчей: {exc}")
        return

    if not games:
        if msg:
            await msg.edit_text(
                f"На дату *{date_str}* не найдено матчей.",
                parse_mode="Markdown",
                reply_markup=home_keyboard(getattr(target, "from_user", None).id if getattr(target, "from_user", None) else None),
            )
        return

    # Разделяем на завершённые и будущие
    FINISHED_STATUSES = {8, 9, 10, 11, 12}
    FINISHED_NAMES = {"finished", "finished after extra time", "finished aet",
                      "after extra time", "after penalties", "ended"}

    def _is_finished(g: dict) -> bool:
        sn = (g.get("statusName") or "").strip().lower()
        sid = g.get("status") or g.get("statusCode") or 0
        if isinstance(sid, str):
            try:
                sid = int(sid)
            except ValueError:
                sid = 0
        return sid in FINISHED_STATUSES or sn in FINISHED_NAMES

    value_calc = ValueCalculator(
        min_odds=getattr(settings, "min_value_odds", 1.3),
        min_probability=getattr(settings, "min_value_probability", 0.1),
    )
    try:
        learner = services.self_learner
    except AttributeError:
        learner = None
    service = PredictionService(
        sstats,
        value_calculator=value_calc,
        odds_parser=OddsParser(),
        self_learner=learner,
    )

    # Прогнозируем все матчи — по 3 параллельно
    sem = asyncio.Semaphore(3)

    async def _predict_one(gid: int):
        async with sem:
            try:
                return await service.predict(gid)
            except Exception as exc:
                logger.debug("backtest predict {} error: {}", gid, exc)
                return None

    game_ids = [g.get("id") or g.get("game_id") for g in games]
    game_ids = [int(gid) for gid in game_ids if gid]
    game_map = {int(g.get("id") or g.get("game_id") or 0): g for g in games
                if g.get("id") or g.get("game_id")}

    total = len(game_ids)
    results = []
    done = 0
    last_edit = _time.monotonic()

    batch_size = 5
    for i in range(0, total, batch_size):
        batch = game_ids[i:i + batch_size]
        batch_results = await asyncio.gather(*[_predict_one(gid) for gid in batch])
        for r in batch_results:
            if r is not None:
                results.append(r)
        done += len(batch)
        now = _time.monotonic()
        elapsed = now - t0
        if now - last_edit > 3.0 and msg:
            try:
                await msg.edit_text(
                    f"⏳ *Обработано {done}/{total} матчей…*\n"
                    f"⏱ Прошло: {elapsed:.0f} сек.",
                    parse_mode="Markdown",
                )
                last_edit = now
            except Exception:
                pass

    elapsed_total = _time.monotonic() - t0

    if not results:
        if msg:
            await msg.edit_text(
                f"На дату *{date_str}* не удалось спрогнозировать ни одного матча."
                f"\n⏱ {elapsed_total:.0f} сек.",
                parse_mode="Markdown",
                reply_markup=home_keyboard(getattr(target, "from_user", None).id if getattr(target, "from_user", None) else None),
            )
        return

    # ── Анализ ВСЕХ матчей ──
    bets_finished = []  # завершённые с результатами
    bets_upcoming = []  # будущие (без результата)

    for pred in results:
        hs = pred.home_score
        aws = pred.away_score
        game_raw = game_map.get(pred.game_id, {})
        finished = _is_finished(game_raw)

        # Если PredictionResult не имеет score — берём из list_games
        if hs is None or aws is None:
            hs = game_raw.get("homeResult") or game_raw.get("homeFTResult")
            aws = game_raw.get("awayResult") or game_raw.get("awayFTResult")
            if hs is not None and aws is not None:
                hs, aws = int(hs), int(aws)
                finished = True

        if not pred.probabilities:
            continue

        # Единый отбор пика через value_engine: только пики с
        # вердиктом «брать» (вероятность ≥ 35%, EV ≥ 3%, kelly > 0).
        # Если «брать» нет — пробуем «осторожно» как fallback. Если и
        # тех нет — пик «не брать», в выборку не попадает.
        odds_map = getattr(pred, "odds_map", None) or {}
        pick = select_best_pick(
            pred.probabilities, odds_map,
            accept_only=True, fallback_to_caution=True,
        )
        if pick is None:
            continue

        best_key = pick.market_key
        best_prob = pick.probability
        # Реальный кф букмекера — санити-фильтрованный пик.odds
        # (None если отклонение от честного выходит из коридора).
        real_odds: float | None = pick.odds
        bookmaker = ""
        # Честный кф = 1/p (расчётный, по формуле).
        fair_odds = pick.fair_odds if pick.fair_odds > 0 else (
            1.0 / best_prob if best_prob > 0 else 0.0
        )
        ev_pct = pick.ev_pct
        verdict = pick.verdict
        composite = pick.composite
        label = _market_label(best_key, pred.home_name, pred.away_name)

        entry = {
            "game_id": pred.game_id,
            "home": pred.home_name,
            "away": pred.away_name,
            "league": pred.league_name or "",
            "market": best_key,
            "label": label,
            "prob": best_prob,
            "fair_odds": fair_odds,
            "real_odds": real_odds,
            "bookmaker": bookmaker,
            "ev_pct": ev_pct,
            "verdict": verdict,
            "composite": composite,
            "hit": None,
            "score": f"{hs}:{aws}" if hs is not None and aws is not None else "—",
            "finished": finished,
        }

        if finished and hs is not None and aws is not None:
            entry["hit"] = _resolve_market(best_key, hs, aws)
            entry["home_score"] = hs
            entry["away_score"] = aws
            bets_finished.append(entry)
        else:
            bets_upcoming.append(entry)

    # ── Статистика (только по завершённым) ──
    evaluated = [b for b in bets_finished if b["hit"] is not None]
    won = [b for b in evaluated if b["hit"] is True]
    lost = [b for b in evaluated if b["hit"] is False]

    total_bets = len(evaluated)
    won_count = len(won)
    lost_count = len(lost)
    hit_rate = (won_count / total_bets * 100) if total_bets > 0 else 0.0

    # Профит/ROI считаем по ЧЕСТНОМУ кф (формула 1/p) — было решено
    # избавиться от «левых» букмекерских кф в выводах.
    def _odd_for(b: dict) -> float:
        return float(b.get("fair_odds") or 0.0)

    profit = sum(_odd_for(b) - 1.0 for b in won) - lost_count
    roi = (profit / total_bets * 100) if total_bets > 0 else 0.0

    # Только пики с вердиктом «брать» — ровно то, что просил пользователь.
    take_bets = [b for b in (bets_finished + bets_upcoming) if b["verdict"] == "брать"]
    caution_bets = [b for b in (bets_finished + bets_upcoming) if b["verdict"] == "осторожно"]

    # Топ-10 валуйных пиков «брать» (или «осторожно» если «брать» нет),
    # сортируем по composite (EV × √p), а НЕ по кфу, чтобы выводить
    # «вероятный + валуйный», как в ТЗ.
    sortable = take_bets if take_bets else caution_bets
    top10 = sorted(sortable, key=lambda b: b.get("composite", 0.0), reverse=True)[:10]

    # ── Сообщение ──
    lines = [
        f"📊 *Массовый анализ за {date_str}*",
        f"⏱ {elapsed_total:.0f} сек.",
        "",
        f"Всего матчей: *{len(games)}*",
        f"Спрогнозировано: *{len(results)}*",
        f"Завершённых: *{len(bets_finished)}* · Предстоящих: *{len(bets_upcoming)}*",
        f"🎯 Вердикт «брать»: *{len(take_bets)}* · "
        f"«осторожно»: *{len(caution_bets)}*",
    ]

    if total_bets > 0:
        lines.append("")
        lines.append(f"✅ Зашло: *{won_count}* · ❌ Нет: *{lost_count}*")
        lines.append(f"📈 Точность модели: *{hit_rate:.1f}%*")
        lines.append(f"💰 Профит: *{profit:+.2f}* · ROI: *{roi:+.1f}%*")
    elif bets_upcoming and not bets_finished:
        lines.append("")
        lines.append("_Все матчи ещё не завершены — статистика будет позже._")

    if top10:
        header_label = (
            "🏆 *Топ-10 главных прогнозов «брать»:*"
            if take_bets
            else "🟡 *Топ-10 прогнозов «осторожно» (нет «брать»):*"
        )
        lines.append("")
        lines.append(header_label)
        for i, b in enumerate(top10, 1):
            if b["hit"] is True:
                icon = "✅"
            elif b["hit"] is False:
                icon = "❌"
            elif b["finished"]:
                icon = "❔"
            else:
                icon = "🔮"
            fair_o = float(b.get("fair_odds") or 0.0)
            lines.append(
                f"{i}. {icon} {_md(b['home'])} — {_md(b['away'])} "
                f"({b['score']})\n"
                f"     {_md(b['label'])} · кф *{fair_o:.2f}*\n"
                f"     модель *{b['prob']:.0%}* · валуй *{b['ev_pct']:+.1f}%*"
            )

    text = "\n".join(lines)
    if len(text) > 4000:
        text = text[:4000] + "\n\n_…обрезано_"

    if msg:
        await msg.edit_text(
            text, parse_mode="Markdown",
            reply_markup=home_keyboard(getattr(target, "from_user", None).id if getattr(target, "from_user", None) else None),
        )

    # ── Полный отчёт в .txt файл ──
    report_lines = [
        f"ПОЛНЫЙ ОТЧЁТ — Массовый анализ за {date_str}",
        f"Обработано за {elapsed_total:.0f} сек.",
        "=" * 60,
        f"Всего матчей: {len(games)}",
        f"Спрогнозировано: {len(results)}",
        f"Завершённых: {len(bets_finished)}",
        f"Предстоящих: {len(bets_upcoming)}",
        f"Вердикт «брать»: {len(take_bets)}",
        f"Вердикт «осторожно»: {len(caution_bets)}",
    ]
    if total_bets > 0:
        report_lines += [
            f"Зашло: {won_count} из {total_bets}",
            f"Не зашло: {lost_count}",
            f"Точность модели: {hit_rate:.1f}%",
            f"Профит (1 ед./ставку): {profit:+.2f}",
            f"ROI: {roi:+.1f}%",
        ]
    report_lines += ["=" * 60, ""]

    def _fmt_odds(b: dict) -> str:
        fair = float(b.get("fair_odds") or 0.0)
        return f"кф {fair:.2f}"

    if bets_finished:
        report_lines.append("--- ЗАВЕРШЁННЫЕ МАТЧИ ---")
        report_lines.append("")
        sorted_fin = sorted(
            bets_finished, key=lambda b: b.get("composite", 0.0), reverse=True,
        )
        for i, b in enumerate(sorted_fin, 1):
            status = "✅" if b["hit"] else ("❌" if b["hit"] is False else "❔")
            report_lines.append(
                f"{i}. {status} {b['home']} — {b['away']} ({b['score']})"
            )
            report_lines.append(f"   Лига: {b['league']}")
            report_lines.append(
                f"   Прогноз: {b['label']}  [вердикт: {b['verdict']}]"
            )
            report_lines.append(
                f"   {_fmt_odds(b)} | модель {b['prob']:.1%} | валуй {b['ev_pct']:+.1f}%"
            )
            report_lines.append("")

    if bets_upcoming:
        report_lines.append("--- ПРЕДСТОЯЩИЕ МАТЧИ ---")
        report_lines.append("")
        sorted_up = sorted(
            bets_upcoming, key=lambda b: b.get("composite", 0.0), reverse=True,
        )
        for i, b in enumerate(sorted_up, 1):
            report_lines.append(
                f"{i}. 🔮 {b['home']} — {b['away']}"
            )
            report_lines.append(f"   Лига: {b['league']}")
            report_lines.append(
                f"   Прогноз: {b['label']}  [вердикт: {b['verdict']}]"
            )
            report_lines.append(
                f"   {_fmt_odds(b)} | модель {b['prob']:.1%} | валуй {b['ev_pct']:+.1f}%"
            )
            report_lines.append("")

    report_text = "\n".join(report_lines)
    doc = BufferedInputFile(
        report_text.encode("utf-8"),
        filename=f"mass_analysis_{date_str}.txt",
    )
    if chat:
        all_bets_count = len(bets_finished) + len(bets_upcoming)
        await chat.answer_document(
            document=doc,
            caption=(
                f"📊 Полный отчёт за {date_str} ({all_bets_count} прогнозов, "
                f"вердикт «брать»: {len(take_bets)})"
            ),
        )

    # ── Сохранение результатов в БД ──
    if bets_finished:
        try:
            from sqlalchemy.dialects.sqlite import insert as sqlite_insert
            session = services.session_factory()
            try:
                for b in bets_finished:
                    stmt = sqlite_insert(BacktestResult).values(
                        date=date_str,
                        game_id=b["game_id"],
                        home_name=b["home"],
                        away_name=b["away"],
                        league_name=b["league"] or None,
                        market_key=b["market"],
                        probability=b["prob"],
                        fair_odds=float(b.get("fair_odds") or 0.0),
                        home_score=b.get("home_score"),
                        away_score=b.get("away_score"),
                        hit=b["hit"],
                    ).on_conflict_do_update(
                        index_elements=["date", "game_id"],
                        set_={
                            "hit": b["hit"],
                            "home_score": b.get("home_score"),
                            "away_score": b.get("away_score"),
                            "probability": b["prob"],
                            "fair_odds": float(b.get("fair_odds") or 0.0),
                            "market_key": b["market"],
                        },
                    )
                    await session.execute(stmt)
                await session.commit()
                logger.info(
                    "backtest: saved {} results for {}",
                    len(bets_finished), date_str,
                )
            finally:
                await session.close()
        except Exception as exc:
            logger.error("backtest save error: {}", exc)

    # ── Корректировка прогнозов на основе бэктестов ──
    try:
        if learner is not None:
            added = await learner.incorporate_backtest(days=30)
            if added > 0:
                logger.info("backtest: incorporated {} samples into calibration", added)
    except Exception as exc:
        logger.debug("backtest: incorporate_backtest error: {}", exc)


# ── Анализ прогнозов: ближайшие N матчей ─────────────────────


async def _run_prediction_analysis(
    target: CallbackQuery | Message,
    count: int,
    settings: Settings,
    state: FSMContext,
    date_str: str,
) -> None:
    """Прогнозы по N матчам выбранной даты, отбор только «брать».

    Фоном держим asyncio.Task, чтобы кнопкой «🛑 Остановить» можно
    было прервать процесс. По окончании показываем валуйный топ
    (composite EV × √p) и оценку точности модели по BacktestResult.
    Если дата в прошлом — работаем бэктестом (выводим и фактический
    результат по итогу).
    """
    import time as _time

    from aiogram.types import BufferedInputFile
    from sqlalchemy import select

    from core.value_calculator import ValueCalculator
    from db.models import BacktestResult
    from services.odds_parser import OddsParser
    from services.prediction_service import PredictionService

    sstats = services.sstats
    if sstats is None:
        _text = "❌ Сервис SStats не подключён."
        if isinstance(target, CallbackQuery) and target.message:
            await target.message.edit_text(_text)
        else:
            await target.answer(_text)
        return

    if isinstance(target, CallbackQuery):
        chat = target.message
        tg_id = target.from_user.id if target.from_user else 0
    else:
        chat = target
        tg_id = target.from_user.id if target.from_user else 0

    loading_text = ADMIN_PREDICTION_ANALYSIS_LOADING.format(
        count=count, date=date_str,
    )
    if isinstance(target, CallbackQuery) and target.message:
        msg = await target.message.edit_text(
            loading_text, parse_mode="Markdown",
            reply_markup=_prediction_stop_keyboard(),
        )
    else:
        msg = await target.answer(
            loading_text, parse_mode="Markdown",
            reply_markup=_prediction_stop_keyboard(),
        )

    async def _runner() -> None:
        nonlocal msg
        t0 = _time.monotonic()
        try:
            all_games = await sstats.list_games(
                date=date_str, limit=400, cache_ttl=120,
            )
        except Exception as exc:
            logger.error("prediction_analysis list_games: {}", exc)
            if msg:
                await msg.edit_text(f"❌ Ошибка загрузки матчей: {exc}")
            return
        all_games = list(all_games or [])

        def _date_key(g: dict) -> str:
            return str(g.get("date") or g.get("gameDate") or "")
        all_games.sort(key=_date_key)
        upcoming = all_games[:count]
        if not upcoming:
            if msg:
                await msg.edit_text(
                    ADMIN_PREDICTION_ANALYSIS_NO_MATCHES,
                    reply_markup=home_keyboard(tg_id),
                )
            return

        value_calc = ValueCalculator(
            min_odds=getattr(settings, "min_value_odds", 1.15),
            min_value_percent=getattr(settings, "min_value_percent", 2.0),
            min_probability=getattr(settings, "min_value_probability", 0.35),
        )
        try:
            learner = services.self_learner
        except AttributeError:
            learner = None
        service = PredictionService(
            sstats,
            value_calculator=value_calc,
            odds_parser=OddsParser(),
            self_learner=learner,
        )

        sem = asyncio.Semaphore(6)

        async def _predict_one(gid: int):
            async with sem:
                try:
                    return await service.predict(gid)
                except Exception as exc:
                    logger.debug("pa predict {} error: {}", gid, exc)
                    return None

        game_ids = [int(g.get("id") or g.get("gameId") or 0) for g in upcoming]
        game_ids = [g for g in game_ids if g]
        total = len(game_ids)
        results: list = []
        last_edit = _time.monotonic()
        for i in range(0, total, 10):
            batch = game_ids[i:i + 10]
            batch_results = await asyncio.gather(
                *[_predict_one(gid) for gid in batch]
            )
            for r in batch_results:
                if r is not None:
                    results.append(r)
            now = _time.monotonic()
            if now - last_edit > 1.5 and msg:
                try:
                    await msg.edit_text(
                        f"⏳ *Анализ прогнозов*\n"
                        f"Дата: *{date_str}*\n"
                        f"Обработано *{min(i + 5, total)}/{total}* матчей…\n"
                        f"⏱ {now - t0:.0f} сек.",
                        parse_mode="Markdown",
                        reply_markup=_prediction_stop_keyboard(),
                    )
                    last_edit = now
                except Exception:
                    pass

        elapsed = _time.monotonic() - t0
        # Отбираем пики через value_engine — единый контур с санити-фильтром.
        # Никаких пост-хок оверрайдов «real_odds» из best_odds — это ломало
        # санити и выводило мусорные кф («букмекер 20.00 при честном 1.94»).
        bets: list[dict] = []
        for pred in results:
            if not pred.probabilities:
                continue
            odds_map = getattr(pred, "odds_map", None) or {}
            pick = select_best_pick(
                pred.probabilities, odds_map,
                accept_only=True, fallback_to_caution=True,
            )
            if pick is None:
                continue
            hs = getattr(pred, "home_score", None)
            aws = getattr(pred, "away_score", None)
            finished = (
                isinstance(hs, int) and isinstance(aws, int)
                and hs >= 0 and aws >= 0
            )
            hit: bool | None = None
            if finished:
                hit = _resolve_market(pick.market_key, int(hs), int(aws))
            _lat = getattr(pred, "league_avg_total", 2.7)
            bets.append({
                "home": pred.home_name,
                "away": pred.away_name,
                "league": pred.league_name or "",
                "market_key": pick.market_key,
                "label": _market_label(
                    pick.market_key, pred.home_name, pred.away_name,
                ),
                "prob": pick.probability,
                "fair_odds": pick.fair_odds,
                "real_odds": pick.odds,
                "ev_pct": pick.ev_pct,
                "verdict": pick.verdict,
                "composite": pick.composite,
                "finished": finished,
                "home_score": hs if finished else None,
                "away_score": aws if finished else None,
                "hit": hit,
                "league_avg_total": float(_lat),
            })
        take_bets = [b for b in bets if b["verdict"] == "брать"]
        caution_bets = [b for b in bets if b["verdict"] == "осторожно"]

        # Точность модели:
        # 1) Если в выборке есть разрешённые пики (прошлая дата) — считаем
        #    точность по ним напрямую (реальные пики этой выборки).
        # 2) Иначе — берём изторическую точность из BacktestResult.
        accuracy_text = "Точность модели пока не оценивалась."
        roi_text: str | None = None
        # Статистика по разрешённым пикам из выборки.
        resolved_bets = [
            b for b in bets
            if b["hit"] is not None and b["verdict"] == "брать"
        ]
        if resolved_bets:
            won_n = sum(1 for b in resolved_bets if b["hit"])
            hit_rate = won_n / len(resolved_bets) * 100
            # ROI по fair_odds (честный кф = 1/p, это формульный доход).
            profit = sum(
                (b["fair_odds"] - 1.0) if b["hit"] else -1.0
                for b in resolved_bets
            )
            roi = profit / len(resolved_bets) * 100
            accuracy_text = (
                f"На этой выборке («брать»): *{hit_rate:.1f}%* "
                f"({won_n}/{len(resolved_bets)})"
            )
            roi_text = (
                f"💰 Профит (1 ед/ставку по честному кф): *{profit:+.2f}* "
                f"· ROI: *{roi:+.1f}%*"
            )
        else:
            try:
                session = services.session_factory()
                try:
                    stmt = (
                        select(BacktestResult)
                        .order_by(BacktestResult.id.desc())
                        .limit(200)
                    )
                    rows = (await session.execute(stmt)).scalars().all()
                finally:
                    await session.close()
                evaluated = [r for r in rows if r.hit is not None]
                if evaluated:
                    won_n = sum(1 for r in evaluated if r.hit)
                    hit = won_n / len(evaluated) * 100
                    accuracy_text = (
                        f"Точность модели на последних *{len(evaluated)}* "
                        f"завершённых прогнозах: *{hit:.1f}%* "
                        f"({won_n} из {len(evaluated)})"
                    )
            except Exception as exc:
                logger.debug("pa accuracy fetch error: {}", exc)

        sortable = take_bets if take_bets else caution_bets
        top10 = sorted(
            sortable, key=lambda b: b["composite"], reverse=True,
        )[:10]

        lines = [
            "🎯 *Анализ прогнозов*",
            f"Дата: *{date_str}*  ·  ⏱ {elapsed:.0f} сек.",
            f"Проанализировано: *{len(results)}/{total}*  ·  "
            f"«брать» *{len(take_bets)}* / «осторожно» *{len(caution_bets)}*",
            "",
            accuracy_text,
        ]
        if roi_text:
            lines.append(roi_text)
        # Средний тотал по лигам
        _league_totals: dict[str, list[float]] = {}
        for b in bets:
            lg = b.get("league") or "—"
            _league_totals.setdefault(lg, []).append(b.get("league_avg_total", 2.7))
        if _league_totals:
            lines.append("")
            lines.append("⚽ *Ср. тотал по лигам:*")
            for lg_name, vals in sorted(
                _league_totals.items(),
                key=lambda x: -len(x[1]),
            )[:8]:
                avg = sum(vals) / len(vals)
                lines.append(f"  {_md(lg_name)}: *{avg:.2f}*")
        if top10:
            hdr = (
                "🏆 *Топ главных прогнозов «брать» (первые 10):*"
                if take_bets
                else "🟡 *Топ прогнозов «осторожно» (нет «брать», первые 10):*"
            )
            lines.append("")
            lines.append(hdr)
            for i, b in enumerate(top10, 1):
                fair = float(b.get("fair_odds") or 0.0)
                # Глобально: показываем ТОЛЬКО честный кф (формула 1/p),
                # никаких «букмекер X.XX» — по требованию пользователя.
                # Иконка результата для прошедшей даты.
                if b["hit"] is True:
                    icon = "✅"
                elif b["hit"] is False:
                    icon = "❌"
                elif b["finished"]:
                    icon = "❔"
                else:
                    icon = "🔮"
                score_part = (
                    f" ({b['home_score']}:{b['away_score']})"
                    if b["finished"] else ""
                )
                lines.append(
                    f"{i}. {icon} {_md(b['home'])} — {_md(b['away'])}{score_part}\n"
                    f"     {_md(b['label'])} · кф *{fair:.2f}*"
                )

        text = "\n".join(lines)
        if len(text) > 4000:
            text = text[:4000] + "\n\n_…обрезано_"
        if msg:
            await msg.edit_text(
                text, parse_mode="Markdown",
                reply_markup=home_keyboard(tg_id),
            )
        # Полный отчёт прикрепляем файлом, если есть пики.
        if chat and bets:
            doc_lines = [
                f"АНАЛИЗ ПРОГНОЗОВ — {len(bets)} прогнозов",
                f"Обработано {len(results)}/{total} за {elapsed:.0f} сек.",
                "=" * 60,
            ]
            for i, b in enumerate(
                sorted(bets, key=lambda x: x["composite"], reverse=True), 1,
            ):
                fair = float(b.get("fair_odds") or 0.0)
                if b["hit"] is True:
                    status = "✅ "
                elif b["hit"] is False:
                    status = "❌ "
                elif b["finished"]:
                    status = "❔ "
                else:
                    status = ""
                score_part = (
                    f" ({b['home_score']}:{b['away_score']})"
                    if b["finished"] else ""
                )
                doc_lines.append(
                    f"{i}. {status}{b['home']} — {b['away']}{score_part}\n"
                    f"   Лига: {b['league']} (ср.тотал: {b.get('league_avg_total', 2.7):.2f})\n"
                    f"   Прогноз: {b['label']}  [вердикт: {b['verdict']}]\n"
                    f"   кф {fair:.2f} | модель {b['prob']:.1%}"
                )
            # Добавляем сводку в текстовый файл
            summary_lines = ["", "=" * 60, "СВОДКА"]
            summary_lines.append(
                f"Обработано: {len(results)}/{total} за {elapsed:.0f} сек."
            )
            summary_lines.append(
                f"Вердикт «брать»: {len(take_bets)} / "
                f"«осторожно»: {len(caution_bets)}"
            )
            if resolved_bets:
                won_n = sum(1 for b in resolved_bets if b["hit"])
                profit = sum(
                    (b["fair_odds"] - 1.0) if b["hit"] else -1.0
                    for b in resolved_bets
                )
                roi = profit / len(resolved_bets) * 100
                summary_lines.append(
                    f"Точность («брать»): {won_n}/{len(resolved_bets)}"
                )
                summary_lines.append(
                    f"Профит (1 ед/ставку): {profit:+.2f}"
                )
                summary_lines.append(f"ROI: {roi:+.1f}%")
            doc_lines.extend(summary_lines)

            doc = BufferedInputFile(
                "\n".join(doc_lines).encode("utf-8"),
                filename=f"prediction_analysis_{int(_time.time())}.txt",
            )
            await chat.answer_document(
                document=doc,
                caption=f"🎯 Анализ {len(bets)} прогнозов",
            )

            # CSV-файл с полной статистикой
            import csv
            import io
            csv_buf = io.StringIO()
            writer = csv.writer(csv_buf)
            writer.writerow([
                "№", "Результат", "Хозяева", "Гости", "Счёт",
                "Лига", "Ср.тотал лиги", "Рынок", "Вердикт", "КФ (1/p)",
                "Модель %", "Composite", "Зашёл",
            ])
            for idx, b in enumerate(
                sorted(bets, key=lambda x: x["composite"], reverse=True), 1,
            ):
                fair_csv = float(b.get("fair_odds") or 0.0)
                if b["hit"] is True:
                    result_str = "WIN"
                elif b["hit"] is False:
                    result_str = "LOSS"
                elif b["finished"]:
                    result_str = "N/A"
                else:
                    result_str = "PENDING"
                score_csv = (
                    f"{b['home_score']}:{b['away_score']}"
                    if b["finished"] else ""
                )
                writer.writerow([
                    idx, result_str, b["home"], b["away"], score_csv,
                    b["league"], f"{b.get('league_avg_total', 2.7):.2f}",
                    b["label"], b["verdict"],
                    f"{fair_csv:.2f}", f"{b['prob']:.1%}",
                    f"{b['composite']:.4f}", result_str,
                ])
            # Сводная строка в CSV
            if resolved_bets:
                won_n = sum(1 for b in resolved_bets if b["hit"])
                profit = sum(
                    (b["fair_odds"] - 1.0) if b["hit"] else -1.0
                    for b in resolved_bets
                )
                roi = profit / len(resolved_bets) * 100
                writer.writerow([])
                writer.writerow(["СВОДКА"])
                writer.writerow(["Точность", f"{won_n}/{len(resolved_bets)}"])
                writer.writerow(["Профит", f"{profit:+.2f}"])
                writer.writerow(["ROI", f"{roi:+.1f}%"])
            csv_doc = BufferedInputFile(
                csv_buf.getvalue().encode("utf-8"),
                filename=f"prediction_analysis_{int(_time.time())}.csv",
            )
            await chat.answer_document(
                document=csv_doc,
                caption="📊 CSV-статистика",
            )

    # Запускаем в задаче, чтобы можно было отменить кнопкой.
    task = asyncio.create_task(_runner())
    _PA_TASKS[int(tg_id)] = task
    try:
        await task
    except asyncio.CancelledError:
        if msg:
            try:
                await msg.edit_text(
                    "🛑 Анализ прогнозов остановлен пользователем.",
                    reply_markup=home_keyboard(tg_id),
                )
            except Exception:
                pass
    except Exception as exc:
        logger.error("prediction_analysis fatal: {}", exc)
        if msg:
            try:
                await msg.edit_text(
                    f"❌ Ошибка анализа: {exc}",
                    reply_markup=home_keyboard(tg_id),
                )
            except Exception:
                pass
    finally:
        _PA_TASKS.pop(int(tg_id), None)


def _resolve_market(key: str, home: int, away: int) -> bool | None:
    """Определить зашла ли ставка по ключу MarketKey и реальному счёту."""
    total = home + away
    k = key.upper()
    # 1X2
    if k == "1":
        return home > away
    if k == "2":
        return away > home
    if k == "X":
        return home == away
    # Двойной шанс
    if k == "1X":
        return home >= away
    if k == "X2":
        return away >= home
    if k == "12":
        return home != away
    # DNB
    if k == "DNB_HOME":
        return home > away
    if k == "DNB_AWAY":
        return away > home
    # BTTS
    if k == "BTTS":
        return home >= 1 and away >= 1
    if k == "BTTS_NO":
        return home == 0 or away == 0
    # Тоталы O/U
    totals_map = {
        "O05": total > 0.5, "U05": total < 0.5,
        "O15": total > 1.5, "U15": total < 1.5,
        "O25": total > 2.5, "U25": total < 2.5,
        "O35": total > 3.5, "U35": total < 3.5,
        "O45": total > 4.5, "U45": total < 4.5,
        "O55": total > 5.5, "U55": total < 5.5,
    }
    if k in totals_map:
        return totals_map[k]
    # Индивидуальные тоталы
    ind_map = {
        "HT_O05": home > 0.5, "HT_U05": home < 0.5,
        "HT_O15": home > 1.5, "HT_U15": home < 1.5,
        "HT_O25": home > 2.5, "HT_U25": home < 2.5,
        "AT_O05": away > 0.5, "AT_U05": away < 0.5,
        "AT_O15": away > 1.5, "AT_U15": away < 1.5,
        "AT_O25": away > 2.5, "AT_U25": away < 2.5,
    }
    if k in ind_map:
        return ind_map[k]
    # Азиатские форы
    import re
    ah = re.match(r"AH_([HA])([+-]\d+\.?\d*)", k)
    if ah:
        side = ah.group(1)
        line = float(ah.group(2))
        if side == "H":
            return (home + line) > away
        return (away + line) > home
    return None


def _market_label(key: str, home: str, away: str) -> str:
    """Человекочитаемая метка рынка."""
    from core.markets import MARKET_LABELS
    template = MARKET_LABELS.get(key)
    if template:
        return template.replace("{home}", home).replace("{away}", away)
    return key


def _md(text: str) -> str:
    """Экранировать спецсимволы для Markdown v1."""
    for ch in ("*", "_", "`", "["):
        text = text.replace(ch, "")
    return text


def _now() -> datetime:
    return datetime.now(tz=UTC)
