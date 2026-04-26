"""Распознаёт исход рынка по финальному счёту.

Поддерживает базовые рынки из core.markets:
- home / draw / away (1x2)
- over_N.5 / under_N.5 (тотал голов)
- btts_yes / btts_no (обе забивают)
- home_win_clean / away_win_clean (сухая победа)
- handicap_home_-1 / handicap_away_+1 и т.п. (базовые гандикапы)
- double_chance_1x / double_chance_x2 / double_chance_12

Возвращает True если ставка выиграла, False — проиграла, None — не
распознан.
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


def _resolve_1x2(key: str, home: int, away: int) -> bool | None:
    w = _winner(home, away)
    if key in {"home", "home_win", "team_home"}:
        return w == "home"
    if key in {"away", "away_win", "team_away"}:
        return w == "away"
    if key in {"draw", "tie"}:
        return w == "draw"
    return None


def _resolve_totals(key: str, home: int, away: int) -> bool | None:
    m = re.match(r"^(over|under)_([0-9]+(?:\.[0-9]+)?)$", key)
    if not m:
        return None
    side, threshold = m.group(1), float(m.group(2))
    total = home + away
    if side == "over":
        return total > threshold
    return total < threshold


def _resolve_btts(key: str, home: int, away: int) -> bool | None:
    if key in {"btts_yes", "both_yes"}:
        return home > 0 and away > 0
    if key in {"btts_no", "both_no"}:
        return not (home > 0 and away > 0)
    return None


def _resolve_clean_sheet(key: str, home: int, away: int) -> bool | None:
    if key in {"home_win_clean", "home_clean"}:
        return home > away and away == 0
    if key in {"away_win_clean", "away_clean"}:
        return away > home and home == 0
    return None


def _resolve_double_chance(key: str, home: int, away: int) -> bool | None:
    w = _winner(home, away)
    if key in {"double_chance_1x", "1x"}:
        return w in {"home", "draw"}
    if key in {"double_chance_x2", "x2"}:
        return w in {"away", "draw"}
    if key in {"double_chance_12", "12"}:
        return w in {"home", "away"}
    return None


def _resolve_handicap(key: str, home: int, away: int) -> bool | None:
    m = re.match(r"^handicap_(home|away)_(-?\d+(?:\.\d+)?)$", key)
    if not m:
        return None
    side, hcap = m.group(1), float(m.group(2))
    if side == "home":
        adjusted_home = home + hcap
        return adjusted_home > away
    adjusted_away = away + hcap
    return adjusted_away > home


def _resolve_team_totals(key: str, home: int, away: int) -> bool | None:
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


_RESOLVERS: list[Callable[[str, int, int], bool | None]] = [
    _resolve_1x2,
    _resolve_totals,
    _resolve_btts,
    _resolve_clean_sheet,
    _resolve_double_chance,
    _resolve_handicap,
    _resolve_team_totals,
]


def resolve_market(key: str, home_score: int, away_score: int) -> bool | None:
    """Универсальный резолвер. Возвращает None если ключ неизвестен."""
    key_norm = key.strip().lower().replace(" ", "_").replace("+", "+")
    for resolver in _RESOLVERS:
        out = resolver(key_norm, home_score, away_score)
        if out is not None:
            return out
    return None


__all__ = ["resolve_market"]
