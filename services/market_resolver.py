"""Распознаёт исход рынка по финальному счёту.

Использует реальные ключи из ``core.markets.MarketKey``:
- 1×2: ``1`` / ``X`` / ``2``
- Двойной шанс: ``1X`` / ``X2`` / ``12``
- Ничья не в счёт: ``DNB_HOME`` / ``DNB_AWAY``
- Обе забьют: ``BTTS`` / ``BTTS_NO``
- Тоталы: ``O05``…``O55`` / ``U05``…``U55``
- ИТ хозяев: ``HT_O05``…``HT_O25`` / ``HT_U05``…``HT_U25``
- ИТ гостей: ``AT_O05``…``AT_O25`` / ``AT_U05``…``AT_U25``
- Азиатские форы ±1.5/±2.5: ``AH_H+1.5``, ``AH_H-1.5``, ``AH_A+1.5``, …
- Точный счёт: ``EXACT_SCORE_h_a`` (динамический, формат ``EXACT_SCORE_2_1``)

Также понимает «лонг»-формат, который раньше был в этом модуле
(``home_win`` / ``over_2.5`` / ``btts_yes`` / ``handicap_home_-1.5`` /
``home_over_2.5`` / ``double_chance_1x``) — для совместимости с тестами.

Возвращает ``True`` если ставка выиграла, ``False`` — проиграла,
``None`` — ключ не распознан.
"""

from __future__ import annotations

import re
from collections.abc import Callable


def _winner(home: int, away: int) -> str:
    if home > away:
        return "home"
    if home < away:
        return "away"
    return "draw"


# ── 1×2 / двойной шанс / DNB ──────────────────────────────────


def _resolve_1x2(key: str, home: int, away: int) -> bool | None:
    w = _winner(home, away)
    # Короткий формат
    if key == "1":
        return w == "home"
    if key == "x":
        return w == "draw"
    if key == "2":
        return w == "away"
    # Длинный формат
    if key in {"home", "home_win", "team_home"}:
        return w == "home"
    if key in {"away", "away_win", "team_away"}:
        return w == "away"
    if key in {"draw", "tie"}:
        return w == "draw"
    return None


def _resolve_double_chance(key: str, home: int, away: int) -> bool | None:
    w = _winner(home, away)
    if key in {"1x", "double_chance_1x"}:
        return w in {"home", "draw"}
    if key in {"x2", "double_chance_x2"}:
        return w in {"away", "draw"}
    if key in {"12", "double_chance_12"}:
        return w in {"home", "away"}
    return None


def _resolve_dnb(key: str, home: int, away: int) -> bool | None:
    if home == away:
        if key in {"dnb_home", "dnb_away"}:
            # Возврат ставки → не победа и не поражение. Возвращаем None
            # (pending), чтобы статистика не считала это проигрышем.
            return None
        return None
    w = _winner(home, away)
    if key == "dnb_home":
        return w == "home"
    if key == "dnb_away":
        return w == "away"
    return None


# ── BTTS ──────────────────────────────────────────────────────


def _resolve_btts(key: str, home: int, away: int) -> bool | None:
    if key in {"btts", "btts_yes", "both_yes"}:
        return home > 0 and away > 0
    if key in {"btts_no", "both_no"}:
        return not (home > 0 and away > 0)
    return None


# ── Сухая победа ──────────────────────────────────────────────


def _resolve_clean_sheet(key: str, home: int, away: int) -> bool | None:
    if key in {"home_win_clean", "home_clean"}:
        return home > away and away == 0
    if key in {"away_win_clean", "away_clean"}:
        return away > home and home == 0
    return None


# ── Тоталы ────────────────────────────────────────────────────


def _resolve_totals(key: str, home: int, away: int) -> bool | None:
    total = home + away
    # Короткий формат: O05/O15/.../U55
    m = re.match(r"^(o|u)(\d{2,3})$", key)
    if m:
        side, raw = m.group(1), m.group(2)
        # 05 → 0.5, 15 → 1.5, ..., 55 → 5.5; 105 → 10.5
        if len(raw) == 2:
            threshold = int(raw[0]) + (0.5 if raw[1] == "5" else 0.0)
        else:
            # 105 = 10.5, итд.
            threshold = int(raw[:-1]) + (0.5 if raw[-1] == "5" else 0.0)
        if side == "o":
            return total > threshold
        return total < threshold
    # Длинный формат: over_2.5 / under_3.5
    m = re.match(r"^(over|under)_([0-9]+(?:\.[0-9]+)?)$", key)
    if not m:
        return None
    side, threshold_s = m.group(1), m.group(2)
    threshold = float(threshold_s)
    if side == "over":
        return total > threshold
    return total < threshold


# ── Индивидуальные тоталы команд ─────────────────────────────


def _resolve_team_totals(key: str, home: int, away: int) -> bool | None:
    # Короткий формат: HT_O05 / HT_U25 / AT_O15 / AT_U05
    m = re.match(r"^(ht|at)_(o|u)(\d{2,3})$", key)
    if m:
        side_t, side_d, raw = m.group(1), m.group(2), m.group(3)
        if len(raw) == 2:
            threshold = int(raw[0]) + (0.5 if raw[1] == "5" else 0.0)
        else:
            threshold = int(raw[:-1]) + (0.5 if raw[-1] == "5" else 0.0)
        target = home if side_t == "ht" else away
        if side_d == "o":
            return target > threshold
        return target < threshold
    # Длинный формат: home_over_2.5 / away_under_1.5
    m = re.match(
        r"^(home|away)_(over|under)_([0-9]+(?:\.[0-9]+)?)$", key
    )
    if not m:
        return None
    side, direction, threshold = m.group(1), m.group(2), float(m.group(3))
    target = home if side == "home" else away
    if direction == "over":
        return target > threshold
    return target < threshold


# ── Азиатские форы ────────────────────────────────────────────


def _resolve_handicap(key: str, home: int, away: int) -> bool | None:
    # Короткий формат: AH_H+1.5 / AH_H-1.5 / AH_A+2.5 / AH_A-2.5
    m = re.match(r"^ah_(h|a)([+\-]\d+(?:\.\d+)?)$", key)
    if m:
        side, hcap_s = m.group(1), m.group(2)
        hcap = float(hcap_s)
        if side == "h":
            return (home + hcap) > away
        return (away + hcap) > home
    # Длинный формат: handicap_home_-1.5 / handicap_away_+1
    m = re.match(r"^handicap_(home|away)_(-?\d+(?:\.\d+)?)$", key)
    if not m:
        return None
    side, hcap = m.group(1), float(m.group(2))
    if side == "home":
        return (home + hcap) > away
    return (away + hcap) > home


# ── Точный счёт ───────────────────────────────────────────────


def _resolve_exact_score(key: str, home: int, away: int) -> bool | None:
    # Формат EXACT_SCORE_h_a (нижний регистр после нормализации:
    # exact_score_h_a). Также поддерживаем короткий "h:a".
    m = re.match(r"^exact_score_(\d+)_(\d+)$", key)
    if m:
        h, a = int(m.group(1)), int(m.group(2))
        return home == h and away == a
    m = re.match(r"^(\d+):(\d+)$", key)
    if m:
        h, a = int(m.group(1)), int(m.group(2))
        return home == h and away == a
    return None


_RESOLVERS: list[Callable[[str, int, int], bool | None]] = [
    _resolve_1x2,
    _resolve_double_chance,
    _resolve_dnb,
    _resolve_totals,
    _resolve_btts,
    _resolve_clean_sheet,
    _resolve_handicap,
    _resolve_team_totals,
    _resolve_exact_score,
]


def resolve_market(key: str, home_score: int, away_score: int) -> bool | None:
    """Универсальный резолвер. Возвращает None если ключ неизвестен."""
    if key is None:
        return None
    key_norm = key.strip().lower().replace(" ", "_")
    for resolver in _RESOLVERS:
        out = resolver(key_norm, home_score, away_score)
        if out is not None:
            return out
    return None


__all__ = ["resolve_market"]
