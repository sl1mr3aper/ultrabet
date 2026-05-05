"""Определение, сыграл ли рынок при заданном финальном счёте.

Используется регулятором вероятностей и self-learner'ом для пересчёта
hit-rate'ов по историческим матчам.

Поддерживает основные рынки 1X2, DC, DNB, BTTS, O/U, ITM/ITB (HT_/AT_),
азиатские форы целочисленные (±1.5, ±2.5).
"""
from __future__ import annotations


def evaluate_market(market_key: str, home_score: int, away_score: int) -> bool | None:
    """Возвращает True, если рынок сыграл; False — не сыграл; None — не
    поддерживается."""
    if home_score is None or away_score is None:
        return None
    h = int(home_score)
    a = int(away_score)
    total = h + a
    diff = h - a
    k = market_key

    # 1X2
    if k == "1":
        return h > a
    if k == "X":
        return h == a
    if k == "2":
        return h < a

    # Double chance
    if k == "1X":
        return h >= a
    if k == "X2":
        return h <= a
    if k == "12":
        return h != a

    # Draw No Bet (push при ничьей считаем как None — не учитываем)
    if k == "DNB_HOME":
        if h == a:
            return None
        return h > a
    if k == "DNB_AWAY":
        if h == a:
            return None
        return h < a

    # BTTS
    if k == "BTTS":
        return h > 0 and a > 0
    if k == "BTTS_NO":
        return not (h > 0 and a > 0)

    # Тоталы общие
    totals = {
        "O05": (total > 0.5, "O"),
        "U05": (total < 0.5, "U"),
        "O15": (total > 1.5, "O"),
        "U15": (total < 1.5, "U"),
        "O25": (total > 2.5, "O"),
        "U25": (total < 2.5, "U"),
        "O35": (total > 3.5, "O"),
        "U35": (total < 3.5, "U"),
        "O45": (total > 4.5, "O"),
        "U45": (total < 4.5, "U"),
        "O55": (total > 5.5, "O"),
        "U55": (total < 5.5, "U"),
    }
    if k in totals:
        return bool(totals[k][0])

    # Индивидуальные тоталы хозяев (HT_)
    ht_map = {
        "HT_O05": h > 0.5,
        "HT_U05": h < 0.5,
        "HT_O15": h > 1.5,
        "HT_U15": h < 1.5,
        "HT_O25": h > 2.5,
        "HT_U25": h < 2.5,
    }
    if k in ht_map:
        return bool(ht_map[k])

    # Индивидуальные тоталы гостей (AT_)
    at_map = {
        "AT_O05": a > 0.5,
        "AT_U05": a < 0.5,
        "AT_O15": a > 1.5,
        "AT_U15": a < 1.5,
        "AT_O25": a > 2.5,
        "AT_U25": a < 2.5,
    }
    if k in at_map:
        return bool(at_map[k])

    # Азиатские форы
    ah_map = {
        "AH_H+1.5": diff + 1.5 > 0,
        "AH_H-1.5": diff - 1.5 > 0,
        "AH_H+2.5": diff + 2.5 > 0,
        "AH_H-2.5": diff - 2.5 > 0,
        "AH_A+1.5": -diff + 1.5 > 0,
        "AH_A-1.5": -diff - 1.5 > 0,
        "AH_A+2.5": -diff + 2.5 > 0,
        "AH_A-2.5": -diff - 2.5 > 0,
    }
    if k in ah_map:
        return bool(ah_map[k])

    # Точный счёт: ключ EXACT_X_Y
    if k.startswith("EXACT_"):
        try:
            _, ph, pa = k.split("_")
            return int(ph) == h and int(pa) == a
        except (ValueError, IndexError):
            return None

    # Не распознали
    return None


__all__ = ["evaluate_market"]
