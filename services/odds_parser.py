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


_MATCH_RESULT_MARKETS = {
    "match winner",
    "match-winner",
    "match result",
    "1x2",
    "fulltime result",
    "full time result",
    "winner",
    "result",
    "full time 1x2",
    "ft result",
    "fulltime",
    "ftres",
    "to win",
    "match odds",
    "h2h",
    "head to head",
    "moneyline",
    "win market",
}


def _market_to_key(market_name: str, outcome_name: str) -> str | None:
    market = _norm(market_name)
    outcome = _norm(outcome_name)

    # 1X2 / match result — терпимый к формулировкам матчинг
    if (
        market in _MATCH_RESULT_MARKETS
        or ("match" in market
        and ("winner" in market or "result" in market or "odds" in market or "1x2" in market))
        or market == "1x2"
    ):
        if outcome in {"home", "1", "home win", "home team", "home team win"}:
            return MarketKey.HOME
        if outcome in {"draw", "x", "tie", "draw/tie"}:
            return MarketKey.DRAW
        if outcome in {"away", "2", "away win", "away team", "away team win"}:
            return MarketKey.AWAY

    if "double" in market or "double chance" in market:
        tokens = {o.strip() for o in re.split(r"[\s/]+", outcome) if o.strip()}
        if outcome in {"1x", "home/draw", "home or draw", "home-draw"} or tokens == {"home", "draw"}:
            return MarketKey.DOUBLE_1X
        if outcome in {"x2", "draw/away", "draw or away", "draw-away"} or tokens == {"draw", "away"}:
            return MarketKey.DOUBLE_X2
        if outcome in {"12", "home/away", "home or away", "home-away"} or tokens == {"home", "away"}:
            return MarketKey.DOUBLE_12

    if (
        "both teams" in market
        or "btts" in market
        or "оба" in market
        or "both to score" in market
        or "both-teams-to-score" in market
    ):
        if outcome in {"yes", "да", "y", "true"}:
            return MarketKey.BTTS_YES
        if outcome in {"no", "нет", "n", "false"}:
            return MarketKey.BTTS_NO

    # Тоталы: "Over/Under 2.5", "Goals Over/Under", "Totals", "Total Goals 2.5"
    is_totals_market = (
        "total" in market
        or "over" in market
        or "under" in market
        or "over/under" in market
        or market in {"o/u", "goals", "total goals"}
    )
    has_team_prefix = (
        "home team" in market
        or "home total" in market
        or "away team" in market
        or "away total" in market
    )
    if is_totals_market and not has_team_prefix:
        match = re.search(r"(\d+(?:\.\d+)?)", outcome) or re.search(r"(\d+(?:\.\d+)?)", market)
        if match:
            t = float(match.group(1))
            over = "over" in outcome or outcome.startswith("+") or outcome.startswith("o ") or outcome == "o"
            under = "under" in outcome or outcome.startswith("-") or outcome.startswith("u ") or outcome == "u"
            if over:
                return _total_key(t, over=True)
            if under:
                return _total_key(t, over=False)

    if has_team_prefix:
        match = re.search(r"(\d+(?:\.\d+)?)", outcome) or re.search(r"(\d+(?:\.\d+)?)", market)
        if match:
            t = float(match.group(1))
            over = "over" in outcome or outcome.startswith("+")
            side = "home" if "home" in market else "away"
            return _team_total_key(side, t, over)

    if "handicap" in market or "asian handicap" in market or market == "ah":
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


def _iter_bookmakers(raw: Iterable[Any] | None) -> Iterable[dict[str, Any]]:
    """Normalize top-level payload: SStats may return list of bookmakers
    or a single object with ``bookmakers``/``data`` nested.
    """
    if not raw:
        return
    if isinstance(raw, dict):
        nested = raw.get("bookmakers") or raw.get("data") or raw.get("odds") or []
        if isinstance(nested, list):
            yield from (b for b in nested if isinstance(b, dict))
        return
    for item in raw:
        if isinstance(item, dict):
            yield item


def _iter_markets(bookmaker: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for key in ("odds", "markets", "bets", "groups", "marketGroups"):
        bets = bookmaker.get(key)
        if isinstance(bets, list):
            for market in bets:
                if isinstance(market, dict):
                    yield market
            return


def _iter_outcomes(market: dict[str, Any]) -> Iterable[dict[str, Any]]:
    for key in ("odds", "outcomes", "selections", "runners", "values"):
        outs = market.get(key)
        if isinstance(outs, list):
            for outcome in outs:
                if isinstance(outcome, dict):
                    yield outcome
            return


def _outcome_name(outcome: dict[str, Any]) -> str:
    for key in ("name", "outcomeName", "label", "selection", "title", "type"):
        val = outcome.get(key)
        if isinstance(val, str) and val.strip():
            return val
    return ""


def _outcome_value(outcome: dict[str, Any]) -> float | None:
    for key in ("value", "price", "odds", "coefficient", "decimal"):
        val = _safe_float(outcome.get(key))
        if val is not None:
            return val
    return None


class OddsParser:
    """Превращает ответ /Odds/{id} в маппинг MarketKey → коэф."""

    def parse(self, raw: Iterable[dict[str, Any]] | None) -> dict[str, float]:
        if not raw:
            return {}
        accumulator: dict[str, list[float]] = {}
        for bookmaker in _iter_bookmakers(raw):
            for market in _iter_markets(bookmaker):
                market_name = market.get("marketName") or market.get("name") or market.get("title") or ""
                for outcome in _iter_outcomes(market):
                    outcome_name = _outcome_name(outcome)
                    value = _outcome_value(outcome)
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
        for bookmaker in _iter_bookmakers(raw):
            book_name = (
                bookmaker.get("bookmakerName")
                or bookmaker.get("name")
                or bookmaker.get("title")
                or "?"
            )
            for market in _iter_markets(bookmaker):
                market_name = market.get("marketName") or market.get("name") or market.get("title") or ""
                for outcome in _iter_outcomes(market):
                    outcome_name = _outcome_name(outcome)
                    value = _outcome_value(outcome)
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
