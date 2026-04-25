"""Парсинг коэффициентов SStats в плоский маппинг по ключам рынков."""

from __future__ import annotations

import re
from collections.abc import Iterable
from statistics import mean
from typing import Any

from core.markets import MarketKey


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(str(value).replace(",", ".").strip())
    except (ValueError, AttributeError):
        return None


def _norm(text: str | None) -> str:
    return (text or "").strip().lower()


def _market_to_key(market_name: str, outcome_name: str) -> str | None:
    market = _norm(market_name)
    outcome = _norm(outcome_name)

    if market in {"match winner", "1x2", "match-winner", "match result", "winner", "fulltime result"}:
        if outcome in {"home", "1", "home win"}:
            return MarketKey.HOME
        if outcome in {"draw", "x", "tie"}:
            return MarketKey.DRAW
        if outcome in {"away", "2", "away win"}:
            return MarketKey.AWAY

    if "double" in market:
        if outcome in {"1x", "home/draw", "home or draw"}:
            return MarketKey.DOUBLE_1X
        if outcome in {"x2", "draw/away", "draw or away"}:
            return MarketKey.DOUBLE_X2
        if outcome in {"12", "home/away", "home or away"}:
            return MarketKey.DOUBLE_12

    if "both teams" in market or "btts" in market or "оба" in market:
        if outcome in {"yes", "да"}:
            return MarketKey.BTTS_YES
        if outcome in {"no", "нет"}:
            return MarketKey.BTTS_NO

    if "goals" in market and ("over" in market or "under" in market or "total" in market):
        match = re.search(r"(\d+(?:\.\d+)?)", outcome)
        if match:
            t = float(match.group(1))
            if "over" in outcome:
                return _total_key(t, over=True)
            if "under" in outcome:
                return _total_key(t, over=False)

    if market in {"goals over/under", "total goals", "totals", "over/under"}:
        match = re.search(r"(\d+(?:\.\d+)?)", outcome)
        if match:
            t = float(match.group(1))
            if "over" in outcome or "+" in outcome:
                return _total_key(t, over=True)
            if "under" in outcome or "-" in outcome:
                return _total_key(t, over=False)

    if "home team" in market and ("over" in market or "under" in market or "total" in market):
        match = re.search(r"(\d+(?:\.\d+)?)", outcome)
        if match:
            t = float(match.group(1))
            return _team_total_key("home", t, "over" in outcome)
    if "away team" in market and ("over" in market or "under" in market or "total" in market):
        match = re.search(r"(\d+(?:\.\d+)?)", outcome)
        if match:
            t = float(match.group(1))
            return _team_total_key("away", t, "over" in outcome)

    if "handicap" in market:
        match = re.search(r"([+-]?\d+(?:\.\d+)?)", outcome)
        if match:
            line = float(match.group(1))
            if "home" in outcome or outcome.startswith("1"):
                return _handicap_key("home", line)
            if "away" in outcome or outcome.startswith("2"):
                return _handicap_key("away", line)

    return None


def _total_key(threshold: float, *, over: bool) -> str | None:
    table_over = {1.5: MarketKey.OVER_15, 2.5: MarketKey.OVER_25, 3.5: MarketKey.OVER_35, 4.5: MarketKey.OVER_45}
    table_under = {1.5: MarketKey.UNDER_15, 2.5: MarketKey.UNDER_25, 3.5: MarketKey.UNDER_35, 4.5: MarketKey.UNDER_45}
    target = table_over if over else table_under
    return target.get(threshold)


def _team_total_key(side: str, threshold: float, over: bool) -> str | None:
    if side == "home":
        if threshold == 0.5 and over:
            return MarketKey.HOME_OVER_05
        if threshold == 1.5 and over:
            return MarketKey.HOME_OVER_15
        if threshold == 1.5 and not over:
            return MarketKey.HOME_UNDER_15
    if side == "away":
        if threshold == 0.5 and over:
            return MarketKey.AWAY_OVER_05
        if threshold == 1.5 and over:
            return MarketKey.AWAY_OVER_15
        if threshold == 1.5 and not over:
            return MarketKey.AWAY_UNDER_15
    return None


def _handicap_key(side: str, line: float) -> str | None:
    table = {
        ("home", 1.5): MarketKey.HANDICAP_HOME_PLUS_15,
        ("home", -1.5): MarketKey.HANDICAP_HOME_MINUS_15,
        ("away", 1.5): MarketKey.HANDICAP_AWAY_PLUS_15,
        ("away", -1.5): MarketKey.HANDICAP_AWAY_MINUS_15,
    }
    return table.get((side, line))


class OddsParser:
    """Превращает ответ /Odds/{id} в маппинг MarketKey → коэф."""

    def parse(self, raw: Iterable[dict[str, Any]] | None) -> dict[str, float]:
        if not raw:
            return {}
        accumulator: dict[str, list[float]] = {}
        for bookmaker in raw:
            bets = bookmaker.get("odds") or []
            for market in bets:
                market_name = market.get("marketName") or market.get("name") or ""
                outcomes = market.get("odds") or market.get("outcomes") or []
                for outcome in outcomes:
                    outcome_name = outcome.get("name") or ""
                    value = _safe_float(outcome.get("value"))
                    if value is None or value <= 1.0:
                        continue
                    key = _market_to_key(market_name, outcome_name)
                    if key is None:
                        continue
                    accumulator.setdefault(key, []).append(value)
        return {k: round(mean(v), 3) for k, v in accumulator.items() if v}

    def best_per_market(
        self, raw: Iterable[dict[str, Any]] | None
    ) -> dict[str, tuple[float, str]]:
        """Лучшая котировка на каждый рынок: {key: (value, bookmaker_name)}."""
        if not raw:
            return {}
        best: dict[str, tuple[float, str]] = {}
        for bookmaker in raw:
            book_name = bookmaker.get("bookmakerName") or bookmaker.get("name") or "?"
            bets = bookmaker.get("odds") or []
            for market in bets:
                market_name = market.get("marketName") or market.get("name") or ""
                outcomes = market.get("odds") or market.get("outcomes") or []
                for outcome in outcomes:
                    outcome_name = outcome.get("name") or ""
                    value = _safe_float(outcome.get("value"))
                    if value is None or value <= 1.0:
                        continue
                    key = _market_to_key(market_name, outcome_name)
                    if key is None:
                        continue
                    current = best.get(key)
                    if current is None or value > current[0]:
                        best[key] = (value, book_name)
        return best


__all__ = ["OddsParser"]
