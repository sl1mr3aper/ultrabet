"""Описание рынков ставок и человекочитаемых меток.

Полный каталог рынков, поддерживаемых ансамблем моделей. Ключи — короткие
строковые идентификаторы (StrEnum), используемые везде в проекте: в калькуляторе
вероятностей, парсере коэффициентов, форматтерах, тестах.

Метки в `MARKET_LABELS` поддерживают плейсхолдеры `{home}` и `{away}`, которые
подставляются функцией :func:`label_for`.
"""

from __future__ import annotations

from enum import StrEnum


class MarketKey(StrEnum):
    """Ключи рынков, используемые во всём проекте."""

    # 1×2 (исход матча)
    HOME = "1"
    DRAW = "X"
    AWAY = "2"

    # Двойной шанс
    DOUBLE_1X = "1X"
    DOUBLE_X2 = "X2"
    DOUBLE_12 = "12"

    # Ничья не в счёт (Draw No Bet)
    DNB_HOME = "DNB_HOME"
    DNB_AWAY = "DNB_AWAY"

    # Обе забьют
    BTTS_YES = "BTTS"
    BTTS_NO = "BTTS_NO"

    # Тоталы (общие)
    OVER_05 = "O05"
    UNDER_05 = "U05"
    OVER_15 = "O15"
    UNDER_15 = "U15"
    OVER_25 = "O25"
    UNDER_25 = "U25"
    OVER_35 = "O35"
    UNDER_35 = "U35"
    OVER_45 = "O45"
    UNDER_45 = "U45"
    OVER_55 = "O55"
    UNDER_55 = "U55"

    # Индивидуальные тоталы хозяев
    HOME_OVER_05 = "HT_O05"
    HOME_UNDER_05 = "HT_U05"
    HOME_OVER_15 = "HT_O15"
    HOME_UNDER_15 = "HT_U15"
    HOME_OVER_25 = "HT_O25"
    HOME_UNDER_25 = "HT_U25"

    # Индивидуальные тоталы гостей
    AWAY_OVER_05 = "AT_O05"
    AWAY_UNDER_05 = "AT_U05"
    AWAY_OVER_15 = "AT_O15"
    AWAY_UNDER_15 = "AT_U15"
    AWAY_OVER_25 = "AT_O25"
    AWAY_UNDER_25 = "AT_U25"

    # Азиатские форы
    HANDICAP_HOME_PLUS_15 = "AH_H+1.5"
    HANDICAP_HOME_MINUS_15 = "AH_H-1.5"
    HANDICAP_AWAY_PLUS_15 = "AH_A+1.5"
    HANDICAP_AWAY_MINUS_15 = "AH_A-1.5"
    HANDICAP_HOME_PLUS_25 = "AH_H+2.5"
    HANDICAP_HOME_MINUS_25 = "AH_H-2.5"
    HANDICAP_AWAY_PLUS_25 = "AH_A+2.5"
    HANDICAP_AWAY_MINUS_25 = "AH_A-2.5"

    # Точные счёта (используются динамически — лейблы строятся отдельно)
    EXACT_SCORE = "EXACT_SCORE"


# ── Метки на русском с эмодзи ─────────────────────────────────
MARKET_LABELS: dict[str, str] = {
    # 1×2
    MarketKey.HOME: "🏠 П1 (Победа {home})",
    MarketKey.DRAW: "🤝 Ничья",
    MarketKey.AWAY: "✈️ П2 (Победа {away})",
    # Двойной шанс
    MarketKey.DOUBLE_1X: "🟢 Двойной шанс 1X ({home} или ничья)",
    MarketKey.DOUBLE_X2: "🟢 Двойной шанс X2 (ничья или {away})",
    MarketKey.DOUBLE_12: "🟢 Двойной шанс 12 (без ничьей)",
    # DNB
    MarketKey.DNB_HOME: "♻️ Без ничьей: победа {home}",
    MarketKey.DNB_AWAY: "♻️ Без ничьей: победа {away}",
    # BTTS
    MarketKey.BTTS_YES: "🎯 Обе забьют (ОЗ)",
    MarketKey.BTTS_NO: "🚫 Обе НЕ забьют",
    # Тоталы
    MarketKey.OVER_05: "⚽ ТБ 0.5",
    MarketKey.UNDER_05: "🛡️ ТМ 0.5",
    MarketKey.OVER_15: "⚽ ТБ 1.5",
    MarketKey.UNDER_15: "🛡️ ТМ 1.5",
    MarketKey.OVER_25: "⚽ ТБ 2.5",
    MarketKey.UNDER_25: "🛡️ ТМ 2.5",
    MarketKey.OVER_35: "🔥 ТБ 3.5",
    MarketKey.UNDER_35: "🛡️ ТМ 3.5",
    MarketKey.OVER_45: "🔥 ТБ 4.5",
    MarketKey.UNDER_45: "🛡️ ТМ 4.5",
    MarketKey.OVER_55: "💥 ТБ 5.5",
    MarketKey.UNDER_55: "🛡️ ТМ 5.5",
    # Индивидуальные тоталы хозяев
    MarketKey.HOME_OVER_05: "🏠 ИТБ 0.5 {home}",
    MarketKey.HOME_UNDER_05: "🏠 ИТМ 0.5 {home}",
    MarketKey.HOME_OVER_15: "🏠 ИТБ 1.5 {home}",
    MarketKey.HOME_UNDER_15: "🏠 ИТМ 1.5 {home}",
    MarketKey.HOME_OVER_25: "🏠 ИТБ 2.5 {home}",
    MarketKey.HOME_UNDER_25: "🏠 ИТМ 2.5 {home}",
    # Индивидуальные тоталы гостей
    MarketKey.AWAY_OVER_05: "✈️ ИТБ 0.5 {away}",
    MarketKey.AWAY_UNDER_05: "✈️ ИТМ 0.5 {away}",
    MarketKey.AWAY_OVER_15: "✈️ ИТБ 1.5 {away}",
    MarketKey.AWAY_UNDER_15: "✈️ ИТМ 1.5 {away}",
    MarketKey.AWAY_OVER_25: "✈️ ИТБ 2.5 {away}",
    MarketKey.AWAY_UNDER_25: "✈️ ИТМ 2.5 {away}",
    # Форы
    MarketKey.HANDICAP_HOME_PLUS_15: "🏠 Фора (+1.5) {home}",
    MarketKey.HANDICAP_HOME_MINUS_15: "🏠 Фора (-1.5) {home}",
    MarketKey.HANDICAP_AWAY_PLUS_15: "✈️ Фора (+1.5) {away}",
    MarketKey.HANDICAP_AWAY_MINUS_15: "✈️ Фора (-1.5) {away}",
    MarketKey.HANDICAP_HOME_PLUS_25: "🏠 Фора (+2.5) {home}",
    MarketKey.HANDICAP_HOME_MINUS_25: "🏠 Фора (-2.5) {home}",
    MarketKey.HANDICAP_AWAY_PLUS_25: "✈️ Фора (+2.5) {away}",
    MarketKey.HANDICAP_AWAY_MINUS_25: "✈️ Фора (-2.5) {away}",
}


# ── Группировка рынков для UI ─────────────────────────────────
MARKET_GROUPS: dict[str, list[MarketKey]] = {
    "Исход": [MarketKey.HOME, MarketKey.DRAW, MarketKey.AWAY],
    "Двойной шанс": [MarketKey.DOUBLE_1X, MarketKey.DOUBLE_X2, MarketKey.DOUBLE_12],
    "DNB": [MarketKey.DNB_HOME, MarketKey.DNB_AWAY],
    "Обе забьют": [MarketKey.BTTS_YES, MarketKey.BTTS_NO],
    "Тоталы": [
        MarketKey.OVER_05, MarketKey.UNDER_05,
        MarketKey.OVER_15, MarketKey.UNDER_15,
        MarketKey.OVER_25, MarketKey.UNDER_25,
        MarketKey.OVER_35, MarketKey.UNDER_35,
        MarketKey.OVER_45, MarketKey.UNDER_45,
        MarketKey.OVER_55, MarketKey.UNDER_55,
    ],
    "ИТ хозяев": [
        MarketKey.HOME_OVER_05, MarketKey.HOME_UNDER_05,
        MarketKey.HOME_OVER_15, MarketKey.HOME_UNDER_15,
        MarketKey.HOME_OVER_25, MarketKey.HOME_UNDER_25,
    ],
    "ИТ гостей": [
        MarketKey.AWAY_OVER_05, MarketKey.AWAY_UNDER_05,
        MarketKey.AWAY_OVER_15, MarketKey.AWAY_UNDER_15,
        MarketKey.AWAY_OVER_25, MarketKey.AWAY_UNDER_25,
    ],
    "Форы 1.5": [
        MarketKey.HANDICAP_HOME_PLUS_15, MarketKey.HANDICAP_HOME_MINUS_15,
        MarketKey.HANDICAP_AWAY_PLUS_15, MarketKey.HANDICAP_AWAY_MINUS_15,
    ],
    "Форы 2.5": [
        MarketKey.HANDICAP_HOME_PLUS_25, MarketKey.HANDICAP_HOME_MINUS_25,
        MarketKey.HANDICAP_AWAY_PLUS_25, MarketKey.HANDICAP_AWAY_MINUS_25,
    ],
}


def label_for(key: str, *, home: str, away: str) -> str:
    """Строит человекочитаемую метку для рынка с подстановкой названий команд."""
    template = MARKET_LABELS.get(key, key)
    return template.format(home=home, away=away)


def all_market_keys() -> list[str]:
    """Все ключи рынков (включая динамический EXACT_SCORE)."""
    return [m.value for m in MarketKey]


def group_for(key: str) -> str | None:
    for group, keys in MARKET_GROUPS.items():
        if key in {k.value for k in keys}:
            return group
    return None


__all__ = [
    "MARKET_GROUPS",
    "MARKET_LABELS",
    "MarketKey",
    "all_market_keys",
    "group_for",
    "label_for",
]
