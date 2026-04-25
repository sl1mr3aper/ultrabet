"""Описание рынков ставок и человекочитаемых меток."""

from __future__ import annotations

from enum import StrEnum


class MarketKey(StrEnum):
    """Ключи рынков, используемые во всём проекте."""

    HOME = "1"
    DRAW = "X"
    AWAY = "2"
    DOUBLE_1X = "1X"
    DOUBLE_X2 = "X2"
    DOUBLE_12 = "12"
    BTTS_YES = "BTTS"
    BTTS_NO = "BTTS_NO"
    OVER_15 = "O15"
    UNDER_15 = "U15"
    OVER_25 = "O25"
    UNDER_25 = "U25"
    OVER_35 = "O35"
    UNDER_35 = "U35"
    OVER_45 = "O45"
    UNDER_45 = "U45"
    HOME_OVER_05 = "HT_O05"
    HOME_OVER_15 = "HT_O15"
    HOME_UNDER_15 = "HT_U15"
    AWAY_OVER_05 = "AT_O05"
    AWAY_OVER_15 = "AT_O15"
    AWAY_UNDER_15 = "AT_U15"
    HANDICAP_HOME_PLUS_15 = "AH_H+1.5"
    HANDICAP_HOME_MINUS_15 = "AH_H-1.5"
    HANDICAP_AWAY_PLUS_15 = "AH_A+1.5"
    HANDICAP_AWAY_MINUS_15 = "AH_A-1.5"


MARKET_LABELS: dict[str, str] = {
    MarketKey.HOME: "🏠 П1 (Победа {home})",
    MarketKey.DRAW: "🤝 Ничья",
    MarketKey.AWAY: "✈️ П2 (Победа {away})",
    MarketKey.DOUBLE_1X: "🟢 Двойной шанс 1X ({home} или ничья)",
    MarketKey.DOUBLE_X2: "🟢 Двойной шанс X2 (ничья или {away})",
    MarketKey.DOUBLE_12: "🟢 Двойной шанс 12 (без ничьей)",
    MarketKey.BTTS_YES: "🎯 Обе забьют (ОЗ)",
    MarketKey.BTTS_NO: "🚫 Обе НЕ забьют",
    MarketKey.OVER_15: "⚽ ТБ 1.5",
    MarketKey.UNDER_15: "🛡️ ТМ 1.5",
    MarketKey.OVER_25: "⚽ ТБ 2.5",
    MarketKey.UNDER_25: "🛡️ ТМ 2.5",
    MarketKey.OVER_35: "🔥 ТБ 3.5",
    MarketKey.UNDER_35: "🛡️ ТМ 3.5",
    MarketKey.OVER_45: "🔥 ТБ 4.5",
    MarketKey.UNDER_45: "🛡️ ТМ 4.5",
    MarketKey.HOME_OVER_05: "🏠 ИТБ 0.5 {home}",
    MarketKey.HOME_OVER_15: "🏠 ИТБ 1.5 {home}",
    MarketKey.HOME_UNDER_15: "🏠 ИТМ 1.5 {home}",
    MarketKey.AWAY_OVER_05: "✈️ ИТБ 0.5 {away}",
    MarketKey.AWAY_OVER_15: "✈️ ИТБ 1.5 {away}",
    MarketKey.AWAY_UNDER_15: "✈️ ИТМ 1.5 {away}",
    MarketKey.HANDICAP_HOME_PLUS_15: "🏠 Фора (+1.5) {home}",
    MarketKey.HANDICAP_HOME_MINUS_15: "🏠 Фора (-1.5) {home}",
    MarketKey.HANDICAP_AWAY_PLUS_15: "✈️ Фора (+1.5) {away}",
    MarketKey.HANDICAP_AWAY_MINUS_15: "✈️ Фора (-1.5) {away}",
}


def label_for(key: str, *, home: str, away: str) -> str:
    template = MARKET_LABELS.get(key, key)
    return template.format(home=home, away=away)


__all__ = ["MARKET_LABELS", "MarketKey", "label_for"]
