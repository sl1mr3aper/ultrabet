"""Просмотр лиг и таблиц."""

from __future__ import annotations

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from api.sstats_client import SStatsClient
from bot.context import services
from bot.formatters import format_league_table, format_match_list
from bot.keyboards import league_view_keyboard
from bot.navigation import nav_push
from bot.pagination import (
    Page,
    format_paginated,
    pagination_keyboard,
    parse_page_input,
    parse_pagination_callback,
)
from bot.states import LeagueSearchStates
from bot.styles import (
    ICON_TROPHY,
    bullet,
    header,
)
from bot.texts import NO_MATCHES, Buttons
from config import Settings
from services.countries import (
    country_flag,
    country_ru,
    fuzzy_country_match,
)
from services.text_processor import fuzzy_score

router = Router(name="leagues")
LEAGUES_PAGE_SIZE = 8


async def _has_filter_marker(
    parts: list[str], state: FSMContext, *, idx: int,
) -> bool:
    """Есть ли в callback маркер активного фильтра по стране?

    Поддерживает оба формата:
    1) Новый: `parts[idx] == "f"` — означает «фильтр активен,
       реальное значение в FSM:leagues_filter_q».
    2) Старый: `parts[idx]` — это буквальный URL-quoted back_query
       (для совместимости со старыми nav-стек-записями).

    Возвращает True если фильтр считается активным.
    """
    if len(parts) <= idx:
        return False
    raw = parts[idx]
    if not raw:
        return False
    if raw == "f":
        data = await state.get_data()
        return bool(data.get("leagues_filter_q"))
    # Legacy: устанавливаем filter в FSM ради унификации даунстрима.
    from urllib.parse import unquote
    try:
        await state.update_data(leagues_filter_q=unquote(raw))
    except Exception:
        pass
    return True


def _leagues_keyboard_paginated(
    page: Page, *, has_filter: bool = False,
) -> InlineKeyboardBuilder:
    """Клавиатура списка лиг.

    Если `has_filter=True`, в callback кладём короткий маркер `:f` —
    хендлер по этому флагу прочитает реальный фильтр из FSM
    (`leagues_filter_q`). Это чтобы не превышать 64-байтный лимит
    Telegram callback_data при русских названиях стран
    (URL-quoted «Великобритания» = 84 байта только на это).
    """
    builder = InlineKeyboardBuilder()
    for league in page.slice():
        if not isinstance(league, dict):
            continue
        league_id = league.get("id")
        name = league.get("name") or "?"
        country = (league.get("country") or {}) if isinstance(league.get("country"), dict) else {}
        flag = country_flag(country.get("name") if isinstance(country, dict) else None)
        cb = f"league:{league_id}:f" if has_filter else f"league:{league_id}"
        builder.button(text=f"{flag} {name}"[:60], callback_data=cb)
    builder.adjust(1)
    return builder


async def _load_leagues() -> list[dict]:
    sstats: SStatsClient = services.sstats
    leagues_raw = await sstats.list_leagues()
    return [l for l in (leagues_raw or []) if isinstance(l, dict) and l.get("id")]


def _filter_leagues_by_country(leagues: list[dict], query: str) -> list[dict]:
    """Многоуровневый fuzzy фильтр лиг по стране/названию.

    Стадии (по убыванию приоритета):
    1. Берём все уникальные `country.name` из пула лиг.
    2. `fuzzy_country_match` (алиасы + translit + unidecode + rapidfuzz) —
       получаем топ-N канонических стран, ранжированных по релевантности.
    3. Фильтруем лиги по совпадению канонической страны.
    4. Доп. fuzzy по названию самой лиги (если запрос похож на имя
       лиги, например «premier»).
    """
    q = query.strip()
    if not q:
        return leagues

    countries_set: set[str] = set()
    for lg in leagues:
        c = lg.get("country")
        if isinstance(c, dict):
            cname = c.get("name")
            if cname:
                countries_set.add(str(cname))
    matches = fuzzy_country_match(
        q, countries=sorted(countries_set), top_k=len(countries_set) or 5,
    )
    # Набор «приемлемых» канонических id (порог 0.6)
    accepted: dict[str, float] = {
        canon: score for canon, score in matches if score >= 0.6
    }

    def _canon(c: dict | None) -> str:
        if not isinstance(c, dict):
            return ""
        return (c.get("name") or "").strip().lower().replace("_", "-").replace(" ", "-")

    scored: list[tuple[dict, float]] = []
    for lg in leagues:
        country = lg.get("country") if isinstance(lg.get("country"), dict) else None
        canon = _canon(country)
        cname = (country or {}).get("name") if isinstance(country, dict) else ""
        lname = str(lg.get("name") or "")
        score = 0.0
        if canon and canon in accepted:
            score = accepted[canon]
        # Fallback: сопоставление с самим именем лиги (для «premier», «serie a» и т.п.)
        score = max(score, fuzzy_score(q.lower(), lname) * 0.85)
        if q.lower() in lname.lower():
            score = max(score, 0.92)
        if isinstance(cname, str) and q.lower() in cname.lower():
            score = max(score, 0.9)
        if score >= 0.55:
            scored.append((lg, score))
    scored.sort(key=lambda ls: ls[1], reverse=True)
    return [lg for lg, _ in scored]


def _country_suggestions(query: str, leagues: list[dict], limit: int = 5) -> list[str]:
    """Топ-N подсказок по стране (канонические имена), когда точного
    совпадения не нашлось."""
    countries_set: set[str] = set()
    for lg in leagues:
        c = lg.get("country")
        if isinstance(c, dict):
            cname = c.get("name")
            if cname:
                countries_set.add(str(cname))
    matches = fuzzy_country_match(
        query, countries=sorted(countries_set), top_k=limit,
    )
    return [canon for canon, _ in matches]


async def _render_leagues_page(
    message_or_cb,
    page_index: int,
    *,
    leagues_override: list[dict] | None = None,
    query: str | None = None,
    state: FSMContext | None = None,
) -> None:
    leagues = leagues_override if leagues_override is not None else await _load_leagues()
    # Clamp страницы на случай устаревшего callback / FSM-индекса.
    _max_idx = max(0, (len(leagues) - 1) // LEAGUES_PAGE_SIZE)
    page_index = max(0, min(page_index, _max_idx))
    page: Page = Page(items=leagues, page_index=page_index, page_size=LEAGUES_PAGE_SIZE)
    title = "Лиги"
    footer = (
        "Нажми на лигу или введи *номер страницы* (например `3`) "
        "либо *название страны* (например `испания`, `brazil`)."
    )
    if query:
        title = f"Лиги · фильтр «{query}»"
        footer = f"Найдено: {len(leagues)}. Введи новый запрос или жми кнопки."
    text = format_paginated(
        page,
        render_item=lambda i, l: bullet(
            f"{country_flag((l.get('country') or {}).get('name'))} {l.get('name') or '?'}"
        ),
        header_text=header(title, icon=ICON_TROPHY),
        footer_text=footer,
    )
    # Сохраняем фильтр в FSM — короткий маркер в callback (`:f`) → хендлер
    # читает реальный фильтр отсюда. Это обходит 64-байтный лимит Telegram
    # на callback_data, которого иначе не хватало для русских названий.
    has_filter = bool(query)
    if state is not None:
        if query:
            await state.update_data(leagues_filter_q=query)
        else:
            await state.update_data(leagues_filter_q=None)
    builder = _leagues_keyboard_paginated(page, has_filter=has_filter)
    # Верхний ряд — «🔍 Поиск» + «🏠 В меню»
    builder.row(
        *InlineKeyboardBuilder().button(
            text="🔍 Поиск по странам", callback_data="leagues:search",
        ).as_markup().inline_keyboard[0]
    )
    # Маркер `f` в payload — пагинация знает «фильтр активен», но конкретное
    # значение фильтра берёт из FSM (а не из callback).
    pag_kb = pagination_keyboard(
        "leagues_page", page, extra_payload="f" if has_filter else "",
    ).inline_keyboard
    for row in pag_kb:
        builder.row(*row)
    # Навигация: Назад + Главное меню
    builder.row(
        InlineKeyboardButton(text=Buttons.BACK, callback_data="nav:back"),
        InlineKeyboardButton(text=Buttons.MAIN_MENU, callback_data="menu:home"),
    )
    target = message_or_cb.message if hasattr(message_or_cb, "message") else message_or_cb
    if hasattr(target, "edit_text"):
        try:
            await target.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
        except Exception:
            await target.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    else:
        await target.answer(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    if hasattr(message_or_cb, "answer") and not isinstance(message_or_cb, Message):
        await message_or_cb.answer()


@router.callback_query(F.data == "menu:leagues")
async def menu_leagues(callback: CallbackQuery, state: FSMContext) -> None:
    await nav_push(state, "menu:home")
    if callback.message:
        await callback.answer("Загружаю лиги…")
        await _render_leagues_page(callback, page_index=0, state=state)
    else:
        await callback.answer()


@router.callback_query(F.data.startswith("leagues_page:"))
async def leagues_page_cb(callback: CallbackQuery, state: FSMContext) -> None:
    if not callback.data or not callback.message:
        await callback.answer()
        return
    idx, extra = parse_pagination_callback(callback.data, "leagues_page")
    # Получаем фильтр: сначала из FSM, для совместимости со старыми
    # navigation-стек-записями fallback на URL-quoted значение в callback.
    q = ""
    if extra:
        if extra == "f":
            data = await state.get_data()
            q = str(data.get("leagues_filter_q") or "")
        else:
            from urllib.parse import unquote

            q = unquote(extra)
    if q:
        all_leagues = await _load_leagues()
        filtered = _filter_leagues_by_country(all_leagues, q)
        if filtered:
            await _render_leagues_page(
                callback, page_index=idx, leagues_override=filtered,
                query=q, state=state,
            )
            return
    await _render_leagues_page(callback, page_index=idx, state=state)
    await callback.answer()


@router.callback_query(F.data == "leagues:search")
async def leagues_search_prompt(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(LeagueSearchStates.waiting_for_query)
    # Сохраняем актуальные границы пагинации, чтобы валидатор знал максимум.
    leagues = await _load_leagues()
    total_pages = max(
        1, (len(leagues) + LEAGUES_PAGE_SIZE - 1) // LEAGUES_PAGE_SIZE,
    )
    await state.update_data(total_pages=total_pages)
    if callback.message:
        await callback.message.answer(
            f"✏️ Введи *номер страницы* (от *1* до *{total_pages}*) "
            f"или *название страны/лиги* (например `испания`, `brazil`, `premier`).",
            parse_mode="Markdown",
        )
    await callback.answer()


@router.message(LeagueSearchStates.waiting_for_query)
async def leagues_search_query(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Пусто. Введи номер страницы или название страны.")
        return

    # 1) Если пользователь ввёл «команда1 - команда2» — fallback на
    #    поиск матча, но с уведомлением, что это уже другой сценарий.
    from bot.handlers.predictions import _parse_query, _process_query

    pair = _parse_query(text)
    if pair is not None:
        await state.clear()
        await message.answer(
            "ℹ️ Похоже, ты ввёл *две команды через «-»*. Переключаюсь на "
            "поиск матча вместо фильтра лиг.",
            parse_mode="Markdown",
        )
        await _process_query(message, state, text)
        return

    # 2) Чистое число — номер страницы (с валидацией границ)
    if text and text[0].isdigit():
        data = await state.get_data()
        total_pages = int(data.get("total_pages") or 1)
        if not data.get("total_pages"):
            leagues = await _load_leagues()
            total_pages = max(
                1, (len(leagues) + LEAGUES_PAGE_SIZE - 1) // LEAGUES_PAGE_SIZE,
            )
        idx, error = parse_page_input(text, total_pages)
        if error:
            await message.answer(error, parse_mode="Markdown")
            return
        if idx is not None:
            await _render_leagues_page(
                message, page_index=idx, state=state,
            )
            await state.clear()
            return

    # 3) Fuzzy поиск по стране/лиге
    all_leagues = await _load_leagues()
    filtered = _filter_leagues_by_country(all_leagues, text)
    if not filtered:
        suggestions = _country_suggestions(text, all_leagues, limit=5)
        if suggestions:
            sug_text = ", ".join(country_ru(s) or s for s in suggestions)
            await message.answer(
                f"🤷 По «{text}» ничего не нашёл. Возможно, ты имел в виду: "
                f"*{sug_text}*?\nВведи ещё раз или жми на меню.",
                parse_mode="Markdown",
            )
        else:
            await message.answer(
                f"🤷 Ничего не нашлось по «{text}». Попробуй другое название.",
            )
        return
    # Перед отрисовкой страны — запоминаем, что «Назад» должен вернуть
    # к общему списку лиг (откуда пользователь зашёл в поиск).
    await nav_push(state, "menu:leagues")
    await _render_leagues_page(
        message, page_index=0, leagues_override=filtered,
        query=text, state=state,
    )
    # Сбрасываем только FSM-состояние ожидания ввода, но сохраняем
    # nav_stack и прочие данные сессии (иначе state.clear() стирает и
    # стек, и «Назад» приводит в главное меню).
    await state.set_state(None)


LEAGUE_MATCHES_PAGE_SIZE = 10


def _sort_league_matches(games: list[dict]) -> list[dict]:
    """Сортируем по дате ASC — ближайшие сверху."""

    def _key(g: dict) -> str:
        if not isinstance(g, dict):
            return "9999"
        return str(g.get("date") or g.get("startDate") or "9999")

    return sorted([g for g in games if isinstance(g, dict)], key=_key)


def _format_league_match_line(idx: int, g: dict, *, tz_offset: int) -> str:
    home = (g.get("homeTeam") or {}).get("name") or "?"
    away = (g.get("awayTeam") or {}).get("name") or "?"
    from bot.formatters import _human_date  # local import to avoid cycle

    date_iso = g.get("date") or g.get("startDate") or ""
    date = _human_date(date_iso, tz_offset=tz_offset) if date_iso else "—"
    return f"*{idx}.* {home} — {away}  ·  {date}"


async def _render_league_matches_page(
    callback: CallbackQuery,
    *,
    league_id: int,
    page_index: int,
    has_filter: bool = False,
) -> None:
    """Рендер страницы матчей лиги.

    `has_filter` — флаг «активен фильтр по стране в списке лиг». Если
    True, в дочерних callback кладём короткий маркер `:f` вместо
    реального названия страны (его лимит на callback_data в Telegram —
    64 байта, и URL-quoted кириллица легко выходит за границу). Сам
    фильтр читается из FSM-ключа `leagues_filter_q`.
    """
    settings: Settings = services.settings
    sstats: SStatsClient = services.sstats
    games = await sstats.list_games(
        league_id=league_id,
        upcoming=True,
        limit=200,
        time_zone=settings.timezone_offset,
    )
    games = _sort_league_matches(games or [])
    if not games:
        if callback.message:
            await callback.message.edit_text(
                "📅 *Ближайшие матчи лиги*\n" + NO_MATCHES,
                parse_mode="Markdown",
                reply_markup=league_view_keyboard(
                    league_id, has_filter=has_filter,
                ),
            )
        await callback.answer()
        return

    max_idx = max(0, (len(games) - 1) // LEAGUE_MATCHES_PAGE_SIZE)
    page_index = max(0, min(page_index, max_idx))
    page: Page = Page(
        items=games, page_index=page_index, page_size=LEAGUE_MATCHES_PAGE_SIZE,
    )

    base = page_index * LEAGUE_MATCHES_PAGE_SIZE
    text = format_paginated(
        page,
        render_item=lambda i, g: _format_league_match_line(
            base + i, g, tz_offset=settings.timezone_offset,
        ),
        header_text="📅 *Ближайшие матчи лиги* (ближайшие сверху)\n",
        footer_text="Жми на номер матча чтобы получить прогноз.",
    )

    builder = InlineKeyboardBuilder()
    for off, g in enumerate(page.slice(), start=1):
        gid = g.get("id") if isinstance(g, dict) else None
        if not gid:
            continue
        builder.button(
            text=str(base + off), callback_data=f"lgmatch:{gid}",
        )
    builder.adjust(5)

    pag = pagination_keyboard(
        f"lgmpage:{league_id}", page,
        extra_payload="f" if has_filter else "",
    ).inline_keyboard
    for row in pag:
        builder.row(*row)
    back_to_list_cb = "leagues_page:0:f" if has_filter else "menu:leagues"
    builder.row(
        *InlineKeyboardBuilder().button(
            text="↩️ К списку лиг", callback_data=back_to_list_cb,
        ).as_markup().inline_keyboard[0]
    )
    if callback.message:
        try:
            await callback.message.edit_text(
                text,
                parse_mode="Markdown",
                reply_markup=builder.as_markup(),
            )
        except Exception:
            await callback.message.answer(
                text,
                parse_mode="Markdown",
                reply_markup=builder.as_markup(),
            )
    await callback.answer()


@router.callback_query(F.data.startswith("league:matches:"))
async def league_matches(callback: CallbackQuery, state: FSMContext) -> None:
    """Открыть список ближайших матчей лиги.

    Формат callback: `league:matches:<id>` или `league:matches:<id>:f`.
    Маркер `f` используется вместо реального фильтра-страны
    (иначе callback_data выходит за лимит 64 байт Telegram после
    URL-encode кириллицы). Сам фильтр живёт в FSM как `leagues_filter_q`.
    Старый формат (буквальный back_q) принимается ради совместимости
    со старыми nav-стек-записями.
    """
    if not callback.data or not callback.message:
        await callback.answer()
        return
    parts = callback.data.split(":")
    try:
        league_id = int(parts[2])
    except (IndexError, ValueError):
        await callback.answer()
        return
    has_filter = await _has_filter_marker(parts, state, idx=3)
    suffix = ":f" if has_filter else ""
    await state.update_data(
        prediction_origin=f"lgmatches:{league_id}:0{suffix}",
    )
    await nav_push(state, f"league:menu:{league_id}{suffix}")
    await _render_league_matches_page(
        callback, league_id=league_id, page_index=0, has_filter=has_filter,
    )


@router.callback_query(F.data.startswith("lgmpage:"))
async def league_matches_page_cb(
    callback: CallbackQuery, state: FSMContext,
) -> None:
    if not callback.data:
        await callback.answer()
        return
    # callback: lgmpage:<league_id>:<idx>[:f]
    parts = callback.data.split(":")
    try:
        league_id = int(parts[1])
        idx = int(parts[2])
    except (ValueError, IndexError):
        await callback.answer()
        return
    has_filter = await _has_filter_marker(parts, state, idx=3)
    suffix = ":f" if has_filter else ""
    await state.update_data(
        prediction_origin=f"lgmatches:{league_id}:{idx}{suffix}",
    )
    await _render_league_matches_page(
        callback, league_id=league_id, page_index=idx, has_filter=has_filter,
    )


@router.callback_query(F.data.startswith("lgmatch:"))
async def league_match_pick(
    callback: CallbackQuery, state: FSMContext,
) -> None:
    if not callback.data or not callback.message:
        await callback.answer()
        return
    try:
        game_id = int(callback.data.rsplit(":", 1)[1])
    except ValueError:
        await callback.answer()
        return
    # Прокидываем напрямую в _run_prediction — тот же путь, что у predict:<id>
    try:
        await callback.answer("Считаю прогноз…")
    except Exception:
        pass
    from bot.handlers.predictions import _run_prediction

    await _run_prediction(
        callback.message, state, game_id,
        edit=True, caller_tg_id=callback.from_user.id,
    )


@router.callback_query(F.data.startswith("league:table:"))
async def league_table(callback: CallbackQuery) -> None:
    """Старый callback `league:table:<id>` — оставлен для совместимости,
    парсит id безопасно (без rsplit, чтобы back_q не путал)."""
    if not callback.data or not callback.message:
        await callback.answer()
        return
    parts = callback.data.split(":")
    try:
        league_id = int(parts[2])
    except (IndexError, ValueError):
        await callback.answer()
        return
    sstats: SStatsClient = services.sstats
    seasons = await sstats.ls_seasons(leagueId=league_id, limit=1)
    season_uid = seasons[0].get("uid") if seasons else None
    text = "Таблица недоступна." if not season_uid else format_league_table(
        await sstats.get_standings(str(season_uid))
    )
    await callback.message.edit_text(
        text, parse_mode="Markdown", reply_markup=league_view_keyboard(league_id)
    )
    await callback.answer()


async def _render_league_root(
    callback: CallbackQuery, state: FSMContext,
    *, league_id: int, has_filter: bool = False,
) -> None:
    """Внутренний рендер экрана выбора (матчи / турнирная таблица).

    Сверху лежит флаг has_filter, который решает — класть ли в дочерние
    callback короткий маркер `:f` (сам фильтр в FSM:leagues_filter_q).
    Это обходит 64-байтный лимит callback_data Telegram, которого
    не хватало при URL-quoted кирилличных названиях стран.
    """
    if not callback.message:
        await callback.answer()
        return

    # Назад с экрана выбора — в список лиг (по возможности с фильтром).
    back_target = "leagues_page:0:f" if has_filter else "menu:leagues"
    await nav_push(state, back_target)

    # Имя лиги/страны для шапки.
    league_name = "лига"
    country_name = ""
    flag = "🏆"
    try:
        leagues = await _load_leagues()
        for lg in leagues:
            if int(lg.get("id") or 0) == league_id:
                league_name = lg.get("name") or league_name
                cobj = lg.get("country") if isinstance(lg.get("country"), dict) else {}
                if isinstance(cobj, dict):
                    country_name = cobj.get("name") or ""
                    flag = country_flag(country_name) or flag
                break
    except Exception:
        pass

    builder = InlineKeyboardBuilder()
    suffix = ":f" if has_filter else ""
    matches_cb = f"league:matches:{league_id}{suffix}"
    standings_cb = f"league:standings:{league_id}:0{suffix}"
    builder.button(text="📅 Ближайшие матчи лиги", callback_data=matches_cb)
    builder.button(text="📋 Турнирная таблица", callback_data=standings_cb)
    builder.button(text=Buttons.BACK, callback_data="nav:back")
    builder.button(text=Buttons.MAIN_MENU, callback_data="menu:home")
    builder.adjust(1, 1, 2)

    title = f"{flag} *{league_name}*"
    if country_name:
        title += f"\n_{country_ru(country_name) or country_name}_"
    text = (
        f"{title}\n\n"
        "Выбери раздел:\n"
        "• 📅 Ближайшие матчи лиги — список матчей с прогнозами.\n"
        "• 📋 Турнирная таблица — текущее положение команд."
    )
    try:
        await callback.message.edit_text(
            text, parse_mode="Markdown", reply_markup=builder.as_markup(),
        )
    except Exception:
        await callback.message.answer(
            text, parse_mode="Markdown", reply_markup=builder.as_markup(),
        )
    await callback.answer()


@router.callback_query(F.data.regexp(r"^league:\d+(:.*)?$"))
async def league_root(callback: CallbackQuery, state: FSMContext) -> None:
    """Экран выбора: «Ближайшие матчи» или «Турнирная таблица».Тонкая обёртка вокруг `_render_league_root`.
    """
    if not callback.data or not callback.message:
        await callback.answer()
        return
    parts = callback.data.split(":")
    try:
        league_id = int(parts[1])
    except ValueError:
        await callback.answer()
        return
    has_filter = await _has_filter_marker(parts, state, idx=2)
    await _render_league_root(
        callback, state, league_id=league_id, has_filter=has_filter,
    )


async def _render_league_standings(
    callback: CallbackQuery, state: FSMContext,
    *, league_id: int, page_idx: int, has_filter: bool = False,
) -> None:
    """Внутренний рендер турнирной таблицы.

    Вынесен для прямого вызова без мутаций callback.data.
    """
    if not callback.message:
        await callback.answer()
        return

    # Восстанавливаем имя/страну/флаг лиги (для шапки).
    league_name = "Турнирная таблица"
    country_name = ""
    flag = "🏆"
    try:
        leagues = await _load_leagues()
        for lg in leagues:
            if int(lg.get("id") or 0) == league_id:
                league_name = lg.get("name") or league_name
                cobj = lg.get("country") if isinstance(lg.get("country"), dict) else {}
                if isinstance(cobj, dict):
                    country_name = cobj.get("name") or ""
                    flag = country_flag(country_name) or flag
                break
    except Exception:
        pass

    standings_service = getattr(services, "league_standings", None)
    rows: list = []
    if standings_service is not None:
        try:
            rows = await standings_service.get_for_league(
                league_id,
                league_name=league_name,
                country_name=country_name,
            )
        except Exception:
            rows = []

    PAGE = 12
    total = len(rows)
    last_page = max(0, (total - 1) // PAGE) if total else 0
    page_idx = max(0, min(page_idx, last_page))
    visible = rows[page_idx * PAGE : (page_idx + 1) * PAGE]

    title = f"{flag} *{league_name}*"
    if country_name:
        title += f"\n_{country_ru(country_name) or country_name}_"
    lines: list[str] = [f"📋 {title}", ""]
    if not visible:
        lines.append("_Турнирная таблица временно недоступна._")
    else:
        # Заголовок столбцов в моноширинном блоке. Отступ под маркер
        # позиции (🥇/🥈/🥉/▫️) — 2 символа + пробел.
        header_line = (
            f"`{'  ':>2}{'#':>3}  {'Команда':<16}{'И':>3}"
            f"{'О':>4}{'З':>4}{'П':>4}`"
        )
        lines.append(header_line)
        # Маркеры мест: золото/серебро/бронза для топ-3, точка — остальные.
        for r in visible:
            name = (r.team_name or "?")[:16]
            if r.rank == 1:
                marker = "🥇"
            elif r.rank == 2:
                marker = "🥈"
            elif r.rank == 3:
                marker = "🥉"
            elif r.rank >= max(1, total - 2):
                # Зона вылета (последние три места) — оранжевый кружок.
                marker = "🟠"
            else:
                marker = "  "
            lines.append(
                f"`{marker}{r.rank:>3}  {name:<16}{r.played:>3}"
                f"{r.points:>4}{r.goals_for:>4}{r.goals_against:>4}`"
            )
        # Легенда букв — внизу таблицы, всегда. Чтобы пользователь не
        # гадал, что значат однобуквенные колонки.
        lines.append("")
        lines.append(
            "_И — игры · О — очки · З — забито · П — пропущено_"
        )
        if total > PAGE:
            lines.append(
                f"_Страница {page_idx + 1} из {last_page + 1}_   ·   "
                f"_всего команд: {total}_"
            )
        else:
            lines.append(f"_Команд в таблице: {total}_")

    # AI-резюме: только на первой странице, чтобы не дёргать модель на каждом
    # листании. Обращение в Gemini короткое — best-effort, при ошибке тихо
    # пропускаем.
    if page_idx == 0 and visible:
        ai_refiner = getattr(services, "ai_refiner", None)
        if ai_refiner is not None:
            try:
                summary_lines: list[str] = []
                for r in visible[:6]:
                    summary_lines.append(
                        f"{r.rank}. {r.team_name} — {r.points} оч., "
                        f"{r.played} игр, {r.goals_for}:{r.goals_against}"
                    )
                prompt = (
                    f"Турнирная таблица лиги «{league_name}». "
                    "Дай очень короткое резюме (2–3 предложения, по-русски): "
                    "кто фаворит, у кого реальная борьба за чемпионство и "
                    "за выживание, не используй английские слова и цифры в "
                    "процентах.\n\n" + "\n".join(summary_lines)
                )
                summary = await ai_refiner.refine_text(prompt)
                if summary:
                    lines.append("")
                    lines.append("🧠 *Резюме*")
                    lines.append(summary.strip())
            except Exception:
                pass

    builder = InlineKeyboardBuilder()
    suffix = ":f" if has_filter else ""
    nav_added = 0
    if page_idx > 0:
        builder.button(
            text="← Назад",
            callback_data=f"league:standings:{league_id}:{page_idx - 1}{suffix}",
        )
        nav_added += 1
    builder.button(
        text=f"Стр. {page_idx + 1}/{last_page + 1}",
        callback_data="noop",
    )
    nav_added += 1
    if page_idx < last_page:
        builder.button(
            text="Вперёд →",
            callback_data=f"league:standings:{league_id}:{page_idx + 1}{suffix}",
        )
        nav_added += 1

    league_menu_cb = f"league:menu:{league_id}{suffix}"
    builder.button(text=Buttons.BACK, callback_data=league_menu_cb)
    builder.button(text=Buttons.MAIN_MENU, callback_data="menu:home")
    builder.adjust(nav_added, 2)
    await nav_push(state, league_menu_cb)

    text = "\n".join(lines)
    try:
        await callback.message.edit_text(
            text, parse_mode="Markdown", reply_markup=builder.as_markup(),
        )
    except Exception:
        await callback.message.answer(
            text, parse_mode="Markdown", reply_markup=builder.as_markup(),
        )
    await callback.answer()


@router.callback_query(F.data.startswith("league:standings:"))
async def league_standings_cb(
    callback: CallbackQuery, state: FSMContext,
) -> None:
    """Турнирная таблица. Формат: league:standings:<id>:<page>[:f]."""
    if not callback.data or not callback.message:
        await callback.answer()
        return
    parts = callback.data.split(":")
    try:
        league_id = int(parts[2])
        page_idx = int(parts[3]) if len(parts) > 3 else 0
    except (ValueError, IndexError):
        await callback.answer()
        return
    has_filter = await _has_filter_marker(parts, state, idx=4)
    await _render_league_standings(
        callback, state,
        league_id=league_id, page_idx=page_idx, has_filter=has_filter,
    )


@router.callback_query(F.data.startswith("league:menu:"))
async def league_menu_cb(callback: CallbackQuery, state: FSMContext) -> None:
    """Возврат на экран выбора (матчи / таблица) внутри лиги.

    Парсим callback.data и зовём _render_league_root напрямую — так
    избегаем мутации `callback.data` (CallbackQuery в aiogram v3 — frozen
    pydantic-модель, любое присваивание data роняет ValidationError).
    """
    if not callback.data:
        await callback.answer()
        return
    parts = callback.data.split(":")
    try:
        league_id = int(parts[2])
    except (ValueError, IndexError):
        await callback.answer()
        return
    has_filter = await _has_filter_marker(parts, state, idx=3)
    await _render_league_root(
        callback, state, league_id=league_id, has_filter=has_filter,
    )
# [removed: command handler — UI is buttons-only]
async def standings_command(message: Message) -> None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: /standings Название_лиги")
        return
    sstats: SStatsClient = services.sstats
    needle = parts[1].lower().strip()
    leagues = await sstats.list_leagues()
    matched = [l for l in leagues if needle in (l.get("name") or "").lower()]
    if not matched:
        await message.answer("Лига не найдена. Попробуй точнее.")
        return
    league = matched[0]
    seasons = await sstats.ls_seasons(leagueId=league.get("id"), limit=1)
    season_uid = seasons[0].get("uid") if seasons else None
    if not season_uid:
        await message.answer("Активный сезон не найден.")
        return
    table = await sstats.get_standings(str(season_uid))
    await message.answer(format_league_table(table), parse_mode="Markdown")
# [removed: command handler — UI is buttons-only]
async def league_command(message: Message) -> None:
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("Использование: /league Название")
        return
    sstats: SStatsClient = services.sstats
    settings: Settings = services.settings
    needle = parts[1].lower().strip()
    leagues = await sstats.list_leagues()
    matched = [l for l in leagues if needle in (l.get("name") or "").lower()]
    if not matched:
        await message.answer("Лига не найдена.")
        return
    league = matched[0]
    games = await sstats.list_games(
        league_id=league.get("id"), upcoming=True, limit=15,
        time_zone=settings.timezone_offset,
    )
    header = f"🏆 *{league.get('name')}* — ближайшие матчи"
    text = format_match_list(games, header=header, tz_offset=settings.timezone_offset)
    await message.answer(text, parse_mode="Markdown")
