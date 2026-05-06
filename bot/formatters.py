"""Форматирование сообщений: прогноз, таблицы, профили."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from typing import Any

from core.markets import label_for
from services.bankroll import StakeInput, StakeKind, compute_stake
from services.countries import format_country
from services.prediction_service import PredictionResult


def _emoji_for_prob(prob: float) -> str:
    p = prob * 100.0
    if p >= 78:
        return "🔥🔥"
    if p >= 65:
        return "🔥"
    if p >= 55:
        return "✅"
    if p >= 45:
        return "⚡"
    if p >= 35:
        return "🟡"
    return "❗"


def _human_date(date_iso: str | None, *, tz_offset: int = 3) -> str:
    """Превратить ISO-дату из ответа источника в строку «дд.мм.гггг чч:мм»
    в локальной зоне `tz_offset` (по умолчанию МСК = UTC+3).

    Особенность источника: при запросе с параметром `TimeZone=3` источник
    возвращает время **уже сконвертированное в МСК**, но как «наивный»
    ISO без зоны. Поэтому если у строки нет явной зоны (`Z` или `+HH:MM`),
    мы трактуем её как уже локализованное в `tz_offset` и НЕ сдвигаем
    второй раз. Для строк с явной UTC-меткой делаем стандартный
    переход в `tz_offset`.
    """
    if not date_iso:
        return "—"
    raw = date_iso.strip()
    has_tz = raw.endswith("Z") or _has_explicit_tz(raw)
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return date_iso
    from datetime import timedelta
    if has_tz:
        # Явная зона → нормально конвертируем в локальную.
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=UTC)
        local = dt.astimezone(tz=UTC) + timedelta(hours=tz_offset)
    else:
        # Источник вернул «наивную» строку — это уже локальное время МСК
        # (мы передавали `TimeZone=3`). Никаких сдвигов.
        local = dt
    return local.strftime("%d.%m.%Y %H:%M")


def _has_explicit_tz(iso_str: str) -> bool:
    """Есть ли в ISO-строке явное смещение зоны (`+03:00`/`-05:00`/...)."""
    # Ищем `+HH:MM` или `-HH:MM` в последних 6 символах после буквы T.
    if "T" not in iso_str and " " not in iso_str:
        return False
    tail = iso_str[-6:]
    return (
        len(tail) == 6
        and tail[0] in "+-"
        and tail[1:3].isdigit()
        and tail[3] == ":"
        and tail[4:6].isdigit()
    )


# Санитарные кэпы кфов: для популярных рынков (1X2, DC, Over/Under,
# BTTS, Handicap) кф выше этого порога — почти наверняка артефакт
# парсера (промахнулись с key или mis-mapped outcome). Для экзотики
# (точный счёт, голеадор, время первого гола) кф может быть и больше.
_COMMON_MARKET_PREFIXES = (
    "HOME", "DRAW", "AWAY",
    "DC_", "1X2",
    "OVER_", "UNDER_",
    "BTTS", "GG", "NG",
    "HANDICAP", "AH_",
    "TEAM_HOME_", "TEAM_AWAY_",
)


def _odd_is_sane(key: str, odd: float | None, prob: float | None = None) -> bool:
    """Многоуровневая регуляция кфов:

    1) Базовые границы: 1.01 < odd ≤ 1000.
    2) Для популярных рынков (1X2/DC/O-U/BTTS/AH/IT) кф ∈ [1.15; 30].
       Lock-out (< 1.15) и экстрим (> 30) — почти всегда мусор парсера.
    3) EV-санити (если передан prob): отбрасываем кфы где
       |EV = prob × odd − 1| > 1.0 (т.е. ставка не может иметь EV
       больше 100% или хуже −100%, это всегда mis-mapping).
    """
    if odd is None:
        return False
    if odd <= 1.01 or odd > 1000.0:
        return False
    upper = key.upper() if isinstance(key, str) else ""
    is_common = any(upper.startswith(p) for p in _COMMON_MARKET_PREFIXES)
    if is_common and (odd < 1.15 or odd > 30.0):
        return False
    # EV-санити: в реальности на популярном рынке EV редко превышает ±20%.
    # Если |EV| > 100% — почти наверняка mis-mapping (например, кф «точного
    # счёта» подцепился к «двойному шансу»). Отбрасываем.
    if prob is not None and 0.0 < prob < 1.0:
        ev = prob * odd - 1.0
        if ev > 1.0 or ev < -0.7:
            return False
    return True


def _ev_of(prob: float, odd: float | None) -> float:
    """EV = p·odd − 1. Если кф неизвестен — используем честный кф (1/p),
    что даёт EV = 0 и оставляет роль тай-брейкера вероятности."""
    if odd is None or odd <= 1.0:
        return 0.0
    return prob * odd - 1.0


def _pick_top_one(
    result: PredictionResult,
) -> tuple[str, float, float | None, str | None] | None:
    """Выбирает «главный прогноз» — рынок с максимальным EV.

    Отбор:
    - `0 < p ≤ 0.85` (отсекаем «перегретые» вероятности);
    - если у рынка есть букмекерский кф — используем `EV = p·odd − 1`;
    - при равенстве EV или при отсутствии кфа — тай-брейк вероятностью.

    В отчёте сами кфы не отображаются, но для упорядочивания пиков они
    нужны (иначе получается «ТМ 3.5 73 %» раньше, чем EV рынки).
    Если у всех кандидатов нет кфа — деградирует в чистую сортировку
    по вероятности.
    """
    from core.value_engine import MIN_FAIR_ODDS

    max_p_for_top = 1.0 / MIN_FAIR_ODDS  # ≈ 0.662 (для MIN_FAIR_ODDS=1.51)

    odds_map = getattr(result, "odds_map", None) or {}
    candidates: list[tuple[str, float, float | None]] = []
    for k, p in result.probabilities.items():
        # Глобальный фильтр кф ≥ 1.51: главный прогноз не должен иметь
        # честный кф меньше 1.51. Запрет «брать» очевидных ставок типа
        # П1 при 87% или ИТМ 2.5 при 85% — у них слишком маленькая
        # возможность заработать (требование пользователя).
        if not (0.0 < p <= max_p_for_top):
            continue
        odd_raw = odds_map.get(k)
        odd = float(odd_raw) if isinstance(odd_raw, (int, float)) else None
        if odd is not None and not _odd_is_sane(k, odd, p):
            odd = None  # рынок подозрительно перекошен — игнорируем кф
        candidates.append((k, p, odd))
    if not candidates:
        return None
    best = max(candidates, key=lambda t: (_ev_of(t[1], t[2]), t[1]))
    return best[0], best[1], best[2], None


def _format_sharp_money(changes: list[dict[str, Any]] | None) -> str | None:
    """Анализ /Odds/live-changes — ищем заметные сдвиги кфов.

    Возвращаем баннер, если найден хотя бы один сдвиг ≥ 5% по модулю
    на популярных рынках (1X2, OU, BTTS, DC). Иначе None.
    """
    if not changes or not isinstance(changes, list):
        return None
    sharp: list[tuple[str, str, float, float]] = []
    for ch in changes:
        if not isinstance(ch, dict):
            continue
        old = ch.get("oldOdd") or ch.get("previous") or ch.get("old")
        new = ch.get("newOdd") or ch.get("current") or ch.get("new")
        market = ch.get("market") or ch.get("marketName") or ""
        outcome = ch.get("outcome") or ch.get("outcomeName") or ""
        try:
            old_f = float(old)
            new_f = float(new)
        except (TypeError, ValueError):
            continue
        if old_f <= 1.01 or new_f <= 1.01:
            continue
        if old_f > 30 or new_f > 30:
            continue
        delta = (new_f - old_f) / old_f
        if abs(delta) >= 0.05:
            sharp.append(
                (_md_safe(market), _md_safe(outcome), old_f, new_f)
            )
    if not sharp:
        return None
    sharp.sort(key=lambda x: abs((x[3] - x[2]) / x[2]), reverse=True)
    lines = ["💹 *Движения линий* _(сдвиги кфов)_"]
    for m, o, old_f, new_f in sharp[:3]:
        direction = "📉" if new_f < old_f else "📈"
        pct = (new_f - old_f) / old_f * 100.0
        lines.append(
            f"  • {direction} {m} → {o}: {old_f:.2f} → *{new_f:.2f}* "
            f"({pct:+.1f}%)"
        )
    return "\n".join(lines)


def _fair_odd(prob: float) -> float | None:
    """Честный кф = 1/p. Ограничиваем разумным диапазоном [1.05; 30]."""
    if prob <= 0.0 or prob >= 1.0:
        return None
    fair = 1.0 / prob
    if fair < 1.05 or fair > 30.0:
        return None
    return round(fair + 1e-9, 2)


def _value_hint(prob: float) -> str:
    """Возвращает текст «(ставка EV, если коэф > X.XX)» для отчёта."""
    fair = _fair_odd(prob)
    if fair is None:
        return ""
    return f"  _(ставка EV, если коэф > {fair:.2f})_"


def _format_kelly_line(prob: float, odd: float | None) -> str | None:
    """Возвращает строку с рекомендацией размера ставки (Kelly в %).

    Если реального кфа нет — считаем Kelly от условного безубыточного
    сценария (кф = 1/p + 5% маржи пользователя), чтобы пользователь
    видел хотя бы порядок величины.
    """
    if prob <= 0.0 or prob >= 1.0:
        return None
    use_odd = odd
    if use_odd is None or use_odd <= 1.0:
        fair = _fair_odd(prob)
        if fair is None:
            return None
        use_odd = fair * 1.05  # подразумеваем 5% над честным КФ — порог EV
    try:
        si = StakeInput(
            bankroll=10000.0,
            probability=prob,
            odds=use_odd,
            base_percent=1.0,
        )
        k = compute_stake(si, StakeKind.KELLY) / 10000.0 * 100.0
    except Exception:
        return None
    if k <= 0.0:
        return None
    return (
        f"💰 Келли *{k:.1f}%* — рекомендуемая доля банка на эту ставку\n"
        f"  _математически оптимальный размер ставки при заявленной "
        f"вероятности и кф_"
    )


def _format_odds_inline(
    result: PredictionResult, key: str
) -> str:
    """Строка вида '  •  кф 2.10' или пусто, если кфа нет (или мусор)."""
    odd_raw = result.odds_map.get(key)
    best = result.best_odds.get(key)
    # EV-санити требует prob — берём из regulated, если есть, иначе raw.
    reg = (result.regulated or {}).get(key)
    prob = (
        reg.get("p_corrected") if isinstance(reg, dict) and reg.get("p_corrected") is not None
        else result.probabilities.get(key)
    )
    odd_ok = _odd_is_sane(key, odd_raw, prob)
    best_ok = best is not None and _odd_is_sane(key, best[0], prob)
    if odd_ok and best_ok and best[0] > odd_raw:
        return f"  ·  кф *{best[0]:.2f}* ({best[1]})"
    if odd_ok:
        return f"  ·  кф *{odd_raw:.2f}*"
    if best_ok:
        return f"  ·  кф *{best[0]:.2f}* ({best[1]})"
    return ""


def _md_safe(value: object) -> str:
    """Удаляет символы Telegram-Markdown V1 (`*`, `_`, `` ` ``, `[`, `]`),
    которые могут прийти из внешних источников (SStats market names,
    AI-ответ, summary) и сломать форматирование всего сообщения."""
    s = str(value or "")
    return (
        s.replace("*", "")
        .replace("_", " ")
        .replace("`", "")
        .replace("[", "(")
        .replace("]", ")")
    )


# Русификация market / outcome имён (англ. термины → рус.).
_PROFIT_MARKET_RU: dict[str, str] = {
    "match winner": "Исход матча",
    "match result": "Исход матча",
    "winner": "Исход матча",
    "1x2": "Исход матча",
    "result": "Результат",
    "result/total goals": "Результат + Тотал",
    "result + total goals": "Результат + Тотал",
    "goals over/under": "Тотал голов",
    "total goals": "Тотал голов",
    "total": "Тотал",
    "team total": "ИТ команды",
    "opponent total": "ИТ соперника",
    "exact score": "Точный счёт",
    "exact goals": "Количество голов",
    "exact goals number": "Количество голов",
    "double chance": "Двойной шанс",
    "draw no bet": "Без ничьей",
    "both teams to score": "Обе забьют",
    "both teams score": "Обе забьют",
    "both teams": "Обе забьют",
    "btts": "Обе забьют",
    "home/away": "Исход (без ничьей)",
    "home or away": "Исход (без ничьей)",
    "asian handicap": "Фора (азиатская)",
    "european handicap": "Фора",
    "handicap": "Фора",
    "first half": "1-й тайм",
    "second half": "2-й тайм",
    "first goal": "Первый гол",
    "last goal": "Последний гол",
    "corners": "Угловые",
    "cards": "Карточки",
    "bookings": "Карточки",
    "clean sheet": "Сухая игра",
    "win to nil": "Победа всухую",
    "half with most goals": "Тайм с большим числом голов",
    "odd/even": "Чётное/нечётное",
}
_PROFIT_OUTCOME_RU: dict[str, str] = {
    "home": "Хозяева",
    "away": "Гости",
    "draw": "Ничья",
    "yes": "Да",
    "no": "Нет",
    "over": "Больше",
    "under": "Меньше",
    "win": "Победа",
    "lose": "Поражение",
    "loss": "Поражение",
    "odd": "Нечёт",
    "even": "Чёт",
    "1": "П1",
    "x": "Ничья",
    "2": "П2",
    "1x": "1X",
    "x2": "X2",
    "12": "12",
}


# Финальный страховочный словарь — пословный перевод. Применяется ПОСЛЕ
# словаря рынков/исходов, чтобы случайно пропущенные SStats-варианты
# (вроде «opponent», «total goals over», «scored both halves») точно
# не оставались по-английски в UI.
_EN_WORD_RU: dict[str, str] = {
    "opponent": "соперника",
    "team": "команды",
    "home": "хозяева",
    "away": "гости",
    "draw": "ничья",
    "yes": "да",
    "no": "нет",
    "over": "больше",
    "under": "меньше",
    "win": "победа",
    "wins": "победы",
    "loss": "поражение",
    "lose": "поражение",
    "loses": "поражения",
    "goals": "голы",
    "goal": "гол",
    "scored": "забили",
    "score": "счёт",
    "scoring": "забили",
    "exact": "точный",
    "double": "двойной",
    "chance": "шанс",
    "total": "тотал",
    "totals": "тоталы",
    "match": "матч",
    "result": "результат",
    "results": "результат",
    "first": "первый",
    "second": "второй",
    "half": "тайм",
    "halves": "таймы",
    "both": "оба",
    "teams": "команды",
    "to": "—",
    "of": "из",
    "and": "и",
    "or": "или",
    "with": "с",
    "without": "без",
    "in": "в",
    "out": "вне",
    "for": "за",
    "against": "против",
    "clean": "сухая",
    "sheet": "игра",
    "nil": "ноль",
    "pen": "пен",
    "penalty": "пенальти",
    "shootout": "серия",
    "extra": "доп.",
    "time": "время",
    "corners": "угловые",
    "cards": "карточки",
    "bookings": "карточки",
    "minute": "минута",
    "minutes": "минуты",
    "odd": "нечёт",
    "even": "чёт",
    "handicap": "фора",
    "european": "европейская",
    "asian": "азиатская",
}


def _force_ru_words(text: str) -> str:
    """Грубая страховка: заменяет оставшиеся английские слова на русский
    эквивалент по `_EN_WORD_RU`. Регистр исходного слова не сохраняется —
    возвращаем словарную форму. Числа, знаки, кириллица — не трогаем."""
    if not text:
        return text
    import re

    def _sub(m: re.Match[str]) -> str:
        w = m.group(0)
        ru = _EN_WORD_RU.get(w.lower())
        return ru if ru is not None else w

    return re.sub(r"[A-Za-z]+", _sub, text)


def _cap_first(text: str) -> str:
    """Капитализирует первую букву строки (и кириллицу, и латиницу),
    остальные символы не трогает. Используется для market/outcome,
    которые после `_force_ru_words` могут начинаться со строчной буквы
    («команды нечёт/чёт» → «Команды нечёт/чёт»)."""
    if not text:
        return text
    for i, ch in enumerate(text):
        if ch.isalpha():
            return text[:i] + ch.upper() + text[i + 1:]
    return text


def _ru_market(name: str) -> str:
    """Переводит SStats market name (англ.) на русский. Если в словаре нет —
    возвращает оригинал. Регистр не важен.

    Префиксное совпадение оставляет «хвост» только если он выглядит как
    числовой параметр («2.5», «1.5») — иначе хвост (англ. слова вроде
    «score», «goals») отбрасывается, чтобы не получалось «Обе забьют score».
    """
    key = (name or "").strip().lower()
    if not key:
        return name
    if key in _PROFIT_MARKET_RU:
        return _PROFIT_MARKET_RU[key]
    # Сортируем по убыванию длины ключа, чтобы более длинные префиксы
    # выигрывали («both teams to score» раньше «both teams»).
    for k in sorted(_PROFIT_MARKET_RU.keys(), key=len, reverse=True):
        if key.startswith(k):
            tail = key[len(k):].strip()
            if tail and any(ch.isdigit() for ch in tail):
                return _PROFIT_MARKET_RU[k] + " " + tail
            return _PROFIT_MARKET_RU[k]
    return name


def _ru_outcome(name: str) -> str:
    """Переводит outcome (Over 2.5, Under 1.5, Draw, Yes...) на русский,
    оставляя числовые порции как есть."""
    s = (name or "").strip()
    if not s:
        return name
    parts = s.split()
    out: list[str] = []
    for p in parts:
        ru = _PROFIT_OUTCOME_RU.get(p.lower())
        out.append(ru if ru is not None else p)
    return " ".join(out)


_EXACT_MARKET_HINTS = ("exact score", "точный счёт", "точный счет", "correct score")


def _is_exact_score_market(market_name: str) -> bool:
    """Детектор рынков вида «Точный счёт» / «Exact Score»."""
    low = (market_name or "").lower()
    return any(h in low for h in _EXACT_MARKET_HINTS)


def _format_profits_block(
    profits: dict[str, Any] | None, *, home: str, away: str,
) -> list[str]:
    """Сформировать блок «📈 Положительные тренды».

    Показываем топ-3 самых прибыльных рынка по каждой стороне, **исключая**
    «Точный счёт» (он шумный и не имеет смысла как тренд). Точные счета
    в этот блок не попадают вообще — ни в строки, ни в подсказки.
    Заголовок указывает фактическое максимальное число матчей в выборке
    (берём максимум `gamesCount` среди показанных строк), а не «~15».
    """
    if not isinstance(profits, dict):
        return []

    def _collect(side_data: Any) -> tuple[list[str], int]:
        if not isinstance(side_data, list):
            return [], 0
        rows: list[tuple[str, str, float, int, int, bool]] = []
        for market in side_data:
            if not isinstance(market, dict):
                continue
            mname_raw = str(market.get("market") or "?")
            is_exact = _is_exact_score_market(mname_raw)
            mname = _md_safe(_ru_market(mname_raw))
            for out in market.get("outcomes") or []:
                if not isinstance(out, dict):
                    continue
                profit = out.get("profit")
                if not isinstance(profit, (int, float)):
                    continue
                oname_raw = str(out.get("name") or "?")
                rows.append(
                    (
                        _cap_first(_force_ru_words(mname)),
                        _cap_first(_force_ru_words(
                            _md_safe(_ru_outcome(oname_raw)),
                        )),
                        float(profit),
                        int(out.get("gamesCount") or 0),
                        int(out.get("winCount") or 0),
                        is_exact,
                    )
                )
        rows.sort(key=lambda x: x[2], reverse=True)
        main_lines: list[str] = []
        max_games = 0
        for mname, oname, prof, gc, wc, is_ex in rows:
            if is_ex:
                continue
            sign = "+" if prof >= 0 else ""
            hit = f"  ·  {wc}/{gc} ({wc / gc * 100:.0f}%)" if gc else ""
            main_lines.append(
                f"  • {mname} → *{oname}* — ROI *{sign}{prof:.2f}*{hit}"
            )
            if gc > max_games:
                max_games = gc
            if len(main_lines) >= 3:
                break
        return main_lines, max_games

    home_lines, home_max = _collect(profits.get("home"))
    away_lines, away_max = _collect(profits.get("away"))
    if not home_lines and not away_lines:
        return []

    total_max = max(home_max, away_max)
    if total_max > 0:
        title_suffix = f" _(последние {total_max} матчей в этой лиге)_"
    else:
        title_suffix = " _(по последним матчам в этой лиге)_"

    parts: list[str] = [
        "",
        f"📈 *Положительные тренды*{title_suffix}",
        "_ROI — средняя прибыль с 1 у.е. ставки на этот исход у этой команды;"
        " доля справа — сколько раз исход заходил из общего числа матчей._",
    ]
    if home_lines:
        parts.append(f"🏠 *{home}* (дома):")
        parts.extend(home_lines)
    if away_lines:
        parts.append(f"✈️ *{away}* (на выезде):")
        parts.extend(away_lines)
    return parts


def _format_form_block(
    last_games: dict[str, Any] | None, *, home: str, away: str,
) -> list[str]:
    """Сформировать блок «📅 Последние матчи команд» (форма за 5 игр).

    `last_games` — это ответ SStats `getLastGamesStats`: словарь с
    ключами `home`/`away` (или `homeTeam`/`awayTeam`), внутри —
    агрегированные показатели за последние N матчей. Полного списка
    отдельных матчей API не отдаёт, поэтому показываем агрегаты:
    среднее xG за / против, голы за / против, форма (W/D/L), серия.
    """
    if not isinstance(last_games, dict) or not last_games:
        return []

    def _side(side_data: Any) -> dict[str, str]:
        out: dict[str, str] = {}
        if not isinstance(side_data, dict):
            return out

        def _f(*keys: str) -> float | None:
            for k in keys:
                v = side_data.get(k)
                if isinstance(v, (int, float)):
                    return float(v)
                if isinstance(v, str):
                    try:
                        return float(v)
                    except ValueError:
                        continue
            return None

        def _i(*keys: str) -> int | None:
            v = _f(*keys)
            return int(v) if v is not None else None

        n = _i("gamesCount", "games", "count", "matches")
        if n:
            out["games"] = str(n)
        wins = _i("wins", "win", "winsCount")
        draws = _i("draws", "draw", "drawsCount")
        losses = _i("losses", "loss", "lose", "lossesCount")
        if wins is not None or draws is not None or losses is not None:
            w, d, l = wins or 0, draws or 0, losses or 0
            out["form"] = f"{w}В · {d}Н · {l}П"
        xg_for = _f("avgXgFor", "xgFor", "avgXG")
        xg_ag = _f("avgXgAgainst", "xgAgainst", "avgXGA")
        if xg_for is not None and xg_ag is not None:
            out["xg"] = f"{xg_for:.2f} − {xg_ag:.2f}"
        gs = _f("avgGoalsFor", "goalsFor", "avgGS")
        gc = _f("avgGoalsAgainst", "goalsAgainst", "avgGC")
        if gs is not None and gc is not None:
            out["goals"] = f"{gs:.2f} − {gc:.2f}"
        streak = side_data.get("streak") or side_data.get("formStreak")
        if isinstance(streak, str) and streak:
            out["streak"] = _md_safe(streak[:8])
        return out

    home_data = last_games.get("home") or last_games.get("homeTeam") or {}
    away_data = last_games.get("away") or last_games.get("awayTeam") or {}
    h = _side(home_data)
    a = _side(away_data)
    if not h and not a:
        return []

    n_label = h.get("games") or a.get("games") or "5"

    def _row(prefix: str, name: str, side: dict[str, str]) -> str:
        bits: list[str] = []
        if "form" in side:
            bits.append(side["form"])
        if "xg" in side:
            bits.append(f"xG {side['xg']}")
        if "goals" in side:
            bits.append(f"голы {side['goals']}")
        if "streak" in side:
            bits.append(f"серия {side['streak']}")
        body = "  ·  ".join(bits) if bits else "нет данных"
        return f"{prefix} *{name}*: {body}"

    parts: list[str] = [
        "",
        f"📅 *Последние матчи команд* _(в среднем за {n_label} игр)_",
    ]
    if h:
        parts.append(_row("🏠", home, h))
    if a:
        parts.append(_row("✈️", away, a))
    return parts


def _live_minute_text(result: PredictionResult) -> str:
    if result.current_minute is not None:
        return f"({result.current_minute}’)"
    if result.status_name:
        return f"({result.status_name})"
    return ""


def format_prediction(
    result: PredictionResult,
    *,
    top_predictions: int = 15,
    top_value: int = 15,
    free_left: int = 0,
    bonus_left: int = 0,
    tz_offset: int = 3,
    daily_used: int | None = None,
    daily_quota: int | None = None,
    is_admin: bool = False,
) -> str:
    del top_value  # раздел EV-ставок удалён из отчёта
    home = result.home_name
    away = result.away_name

    league_country = format_country(result.country_raw, with_flag=True)
    date_h = _human_date(result.date_iso, tz_offset=tz_offset)
    date_now = datetime.now(tz=UTC).strftime("%Y-%m-%d")

    parts: list[str] = []
    if result.is_live:
        header = "🔴 *МАТЧ В ЛАЙВЕ*"
    elif result.is_finished:
        header = "⚽ *АНАЛИЗ СЫГРАННОГО МАТЧА*"
    else:
        header = "⚽ *ПРОГНОЗ НА МАТЧ*"
    parts.append(f"{header} _(актуально на {date_now})_")
    parts.append(f"⚔️ *Команды*: {home} — {away}")
    parts.append(f"📅 *Дата*: {date_h}")
    parts.append(f"🏆 *Лига*: {result.league_name} ({league_country})")
    # Если счёт у нас уже есть (из SStats или MatchResult-фоллбэка),
    # фразу про «источник данных не обновил статус» не показываем —
    # данные о матче полные, нет смысла путать пользователя.
    if result.stale_live and (
        result.home_score is None or result.away_score is None
    ):
        parts.append(
            "📌 *Матч уже завершён*, но источник данных ещё не обновил "
            "статус — отчёт построен по последним доступным данным."
        )

    # Текущий счёт + минута для лайва, итог для сыгранных
    if result.is_live and result.home_score is not None and result.away_score is not None:
        parts.append(
            f"⏱ *Лайв-счёт:* *{result.home_score}:{result.away_score}* "
            f"{_live_minute_text(result)}".rstrip()
        )
    elif result.is_live:
        parts.append(f"⏱ *Лайв*: матч идёт {_live_minute_text(result)}".rstrip())
    elif (
        result.is_finished
        and result.home_score is not None
        and result.away_score is not None
    ):
        parts.append(
            f"✅ *Матч сыгран — итог:* *{result.home_score}:{result.away_score}*  "
            f"({home} — {away})"
        )

    if result.glicko_available:
        parts.append(
            f"🌟 *Glicko-2*: {result.home_rating:.0f} vs {result.away_rating:.0f}"
        )
    else:
        parts.append(
            "🌟 *Glicko-2*: данные недоступны — попробуйте позже "
            "или в день матча."
        )

    pick = _pick_top_one(result)

    # ── Лайв-режим: короткий отчёт без топ-15 ───────────────
    if result.is_live:
        parts.append("")
        parts.append("🎯 *ГЛАВНЫЙ ПРОГНОЗ*")
        if pick is None:
            parts.append("— нет данных")
        else:
            key, prob, _odd, _book = pick
            label = label_for(key, home=home, away=away)
            line = f"• *{label}* — *{prob * 100:.1f}%*{_value_hint(prob)}"
            parts.append(line)
            _kel = _format_kelly_line(prob, None)
            if _kel:
                parts.append(_kel)
        parts.append("")
        parts.append("🧮 *САМЫЙ ВЕРОЯТНЫЙ ТОЧНЫЙ СЧЁТ*")
        if result.top_scores:
            h, a, p = result.top_scores[0]
            parts.append(f"• *{h}:{a}* — {p * 100:.1f}%")
        else:
            parts.append("— нет данных")
        parts.append("")
        if is_admin:
            parts.append("👑 *Admin-режим:* запросы безлимитны")
        elif daily_quota and daily_quota > 0:
            parts.append(
                f"💎 Квота подписки: *{daily_used or 0}/{daily_quota}*  ·  "
                f"🆓 Бесплатных: *{free_left}*"
            )
        else:
            parts.append(f"🆓 Бесплатных запросов осталось: *{free_left}*")
        return "\n".join(parts)

    # ── Стандартный отчёт (прематч / сыгранный) ─────────────
    # Сортируем по EV (EV = p·odd − 1) в убывающем порядке.
    # Потолок вероятности `MAX_PROB_FOR_TOP` (≈0.662 = 1/1.51) — отсекаем
    # «перегретые» рынки, у которых честный кф < 1.51. Это глобальный
    # фильтр кф ≥ 1.51, требуемый ТЗ: пользователь не должен видеть в
    # ТОПе пиков с кф 1.30-1.50 (минимум profit-margin для пользователя).
    # Если у рынка нет кфа — EV считаем равным 0 и рынок уходит в
    # низ сортировки (но всё ещё виден, если EV не хватает).
    from core.value_engine import MIN_FAIR_ODDS
    MAX_PROB_FOR_TOP = 1.0 / MIN_FAIR_ODDS  # ≈ 0.662

    odds_map_for_sort = getattr(result, "odds_map", None) or {}

    def _sort_item(kv: tuple[str, float]) -> tuple[float, float]:
        k, p = kv
        odd_raw = odds_map_for_sort.get(k)
        odd = float(odd_raw) if isinstance(odd_raw, (int, float)) else None
        if odd is not None and not _odd_is_sane(k, odd, p):
            odd = None
        return (_ev_of(p, odd), p)

    sorted_probs = sorted(
        (
            kv
            for kv in result.probabilities.items()
            if 0.0 < kv[1] <= MAX_PROB_FOR_TOP
        ),
        key=_sort_item,
        reverse=True,
    )
    top = sorted_probs[:top_predictions]

    # Блок «5 последних матчей команд» — сразу перед топ-15.
    _last_games = (result.extra or {}).get("last_games")
    parts.extend(_format_form_block(_last_games, home=home, away=away))

    parts.append("")
    if result.regulated:
        # Узнаём максимум hist_games (одинаков для всех ключей одной лиги)
        _games = 0
        for _v in result.regulated.values():
            if isinstance(_v, dict):
                hg = _v.get("hist_games")
                if isinstance(hg, int) and hg > _games:
                    _games = hg
        if _games > 0:
            parts.append(
                f"📊 *ТОП-{top_predictions} ПРОГНОЗОВ* "
                f"_(регулятор · история: {_games} матчей лиги)_"
            )
        else:
            parts.append(
                f"📊 *ТОП-{top_predictions} ПРОГНОЗОВ*"
            )
    else:
        parts.append(
            f"📊 *ТОП-{top_predictions} ПРОГНОЗОВ*"
        )
    if not top:
        parts.append("— в этом матче модель не смогла построить прогнозы")
    reg_map = result.regulated or {}
    for idx, (key, prob) in enumerate(top, start=1):
        label = label_for(key, home=home, away=away)
        # Badge: только сырая модельная вероятность (без коррекций).
        # Финальный (с историей и калибровкой) — это основное число
        # `*X.X%*` слева от баджа, дублировать его в скобках смысла нет.
        # Стрелка показывает, в какую сторону история сдвинула прогноз
        # относительно сырой формулы.
        # Бадж "(↑/↓ модель Y%)" показываем ТОЛЬКО если регулятор реально
        # сдвинул вероятность по истории матчей (есть значимый delta).
        # Если базы нет / коррекция нулевая — бадж не выводим вообще.
        reg_badge = ""
        rinfo = reg_map.get(key)
        if isinstance(rinfo, dict):
            p_model = rinfo.get("p_model")
            delta = rinfo.get("delta_pp")
            if (
                isinstance(p_model, (int, float))
                and isinstance(delta, (int, float))
                and abs(delta) >= 0.3
            ):
                arrow = "↑" if delta > 0 else "↓"
                reg_badge = (
                    f"  _({arrow} модель {p_model * 100:.0f}%)_"
                )
        parts.append(
            f"{idx}. {label} — *{prob * 100:.1f}%*{_value_hint(prob)}{reg_badge}"
        )

    parts.append("")
    parts.append("🎯 *ГЛАВНЫЙ ПРОГНОЗ*")
    if pick is None:
        parts.append("— нет данных")
    else:
        key, prob, _odd, _book = pick
        label = label_for(key, home=home, away=away)
        line = f"• *{label}* — *{prob * 100:.1f}%*{_value_hint(prob)}"
        parts.append(line)
        # Если матч уже сыгран и есть счёт — показываем, зашёл ли прогноз.
        if (
            result.is_finished
            and result.home_score is not None
            and result.away_score is not None
        ):
            from services.market_resolver import resolve_market

            try:
                hit = resolve_market(
                    key, int(result.home_score), int(result.away_score),
                )
            except Exception:
                hit = None
            if hit is True:
                parts.append(
                    f"🟢 *Прогноз сыграл* (итог "
                    f"{result.home_score}:{result.away_score})",
                )
            elif hit is False:
                parts.append(
                    f"🔴 *Прогноз не сыграл* (итог "
                    f"{result.home_score}:{result.away_score})",
                )
        _kel = _format_kelly_line(prob, None)
        if _kel:
            parts.append(_kel)

    parts.append("")
    parts.append("🧮 *ВЕРОЯТНЫЕ ТОЧНЫЕ СЧЕТА*")
    if result.top_scores:
        for h, a, p in result.top_scores[:5]:
            parts.append(f"• {h}:{a} — *{p * 100:.1f}%*")
    else:
        parts.append("— нет данных")

    parts.append("")
    parts.append("🏹 *xG-АНАЛИЗ*")
    parts.append(f"• {home} → *{result.home_xg:.2f}*")
    parts.append(f"• {away} → *{result.away_xg:.2f}*")
    parts.append(f"• Общий тотал → *{result.home_xg + result.away_xg:.2f}*")
    # Средний тотал лиги (из MatchResult-агрегатов, fallback на SStats).
    # Показываем всегда — это часть требования ТЗ. Если данных < 10
    # матчей — берём дефолт 2.65 и помечаем «недостаточно данных».
    _avg = getattr(result, "league_avg_total", None)
    _n = (result.extra or {}).get("league_n_matches") if result.extra else None
    if isinstance(_avg, (int, float)) and _avg > 0:
        if isinstance(_n, int) and _n >= 10:
            parts.append(
                f"• 📊 Ср. тотал лиги → *{_avg:.2f}* "
                f"_(по {_n} матчам)_"
            )
        else:
            parts.append(
                f"• 📊 Ср. тотал лиги → *{_avg:.2f}* "
                "_(дефолт, мало данных)_"
            )

    if result.accuracy_notes:
        parts.append("")
        parts.append("🧠 *Корректировки точности*")
        for note in result.accuracy_notes[:6]:
            parts.append(f"• {note}")

    if result.injuries:
        parts.append("")
        parts.append(f"🚑 *Травмы и пропуски*: {len(result.injuries)} игроков")

    parts.extend(_format_profits_block(result.profits, home=home, away=away))

    if result.summary_text:
        parts.append("")
        parts.append("📝 *Краткое резюме*")
        text = _md_safe(result.summary_text.strip())
        parts.append(text[:600] + ("…" if len(text) > 600 else ""))

    parts.append("")
    if is_admin:
        parts.append("👑 *Admin-режим:* запросы безлимитны")
    elif daily_quota and daily_quota > 0:
        parts.append(
            f"💎 Квота подписки: *{daily_used or 0}/{daily_quota}*  ·  "
            f"🆓 Бесплатных: *{free_left}*"
        )
    else:
        parts.append(f"🆓 Бесплатных запросов осталось: *{free_left}*")
    return "\n".join(parts)


def format_match_list(
    matches: Iterable[dict[str, Any]], *, header: str, tz_offset: int = 3
) -> str:
    items = list(matches)
    if not items:
        return header + "\nНет матчей."
    lines = [header]
    for m in items[:30]:
        home = (m.get("homeTeam") or {}).get("name") or "?"
        away = (m.get("awayTeam") or {}).get("name") or "?"
        date_iso = m.get("date") or ""
        date = _human_date(date_iso, tz_offset=tz_offset)
        league = ((m.get("season") or {}).get("league") or {}).get("name") if isinstance(m.get("season"), dict) else None
        country = None
        season = m.get("season") or {}
        if isinstance(season, dict):
            league_obj = season.get("league") or {}
            if isinstance(league_obj, dict):
                c = league_obj.get("country")
                if isinstance(c, dict):
                    country = c.get("name")
        prefix = format_country(country) if country else "🌐"
        lines.append(f"{prefix} *{home}* — *{away}* · {league or '—'} · {date}")
    return "\n".join(lines)


def format_balance(
    *,
    free: int,
    bonus: int,
    plan: str | None,
    until: datetime | None,
    used: int,
    quota: int,
) -> str:
    from bot.texts import NO_SUBSCRIPTION, QUOTA_INFO

    if plan and until:
        until_text = until.strftime("%d.%m.%Y")
        plan_text = f"{plan} (до {until_text})"
    else:
        plan_text = NO_SUBSCRIPTION
        until_text = "—"
    return QUOTA_INFO.format(
        free=free,
        bonus=bonus,
        plan=plan_text,
        until=until_text,
        used=used,
        quota=max(quota, 0),
    )


def format_league_table(table: dict[str, Any] | None) -> str:
    if not table:
        return "Таблица пока недоступна."
    rows: list[dict[str, Any]] = []
    for key in ("standings", "table", "rows", "data"):
        if isinstance(table.get(key), list):
            rows = table[key]
            break
    if not rows:
        return "Таблица пуста."
    out = ["📋 *Турнирная таблица*"]
    for i, row in enumerate(rows[:20], start=1):
        team = (row.get("team") or {}).get("name") if isinstance(row.get("team"), dict) else row.get("team")
        played = row.get("played") or row.get("p") or 0
        points = row.get("points") or row.get("pts") or 0
        out.append(f"{i:2d}. {team or '?'} — {played} И, *{points} очк.*")
    return "\n".join(out)


__all__ = [
    "format_balance",
    "format_league_table",
    "format_match_list",
    "format_prediction",
]
