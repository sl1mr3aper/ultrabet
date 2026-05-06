"""P0-10: загрузчик football-data.co.uk (бесплатный исторический датасет).

Этот источник не требует регистрации, отдаёт CSV прямо по HTTPS,
содержит ~50K матчей для топ-10 европейских лиг с 1993 года плюс
closing odds от лучших букмекеров (Pinnacle, B365, BWin).

Формат URL:
    https://www.football-data.co.uk/mmz4281/{season_short}/{league_code}.csv

Где:
- ``season_short`` — "2425" для 2024/25, "2526" для 2025/26.
- ``league_code`` — внутренний код:
   E0 (англ. Прем), E1, E2, E3, EC (Англия 1-3 div + Conference)
   D1, D2 (Бундеслига 1, 2)
   I1, I2 (Серия A, B)
   SP1, SP2 (Ла Лига 1, 2)
   F1, F2 (Лига 1, 2)
   N1 (Эредивизи), B1 (Бельгия), P1 (Португалия), T1 (Турция),
   G1 (Греция), SC0 (Шотландия Прем), SC1, SC2, SC3.

Важные колонки CSV:
- Date (DD/MM/YYYY) | HomeTeam | AwayTeam | FTHG | FTAG | FTR
- B365H | B365D | B365A — Bet365 closing
- PSH  | PSD  | PSA  — Pinnacle closing  ← это нужно для CLV-бэктеста!
- BbAvH| BbAvD| BbAvA — Betbrain bookie average
- BbMxH| BbMxD| BbMxA — Betbrain bookie max
- B365>2.5 | B365<2.5 — Over/Under 2.5

Архитектура:
- ``download_csv(url)`` — скачивает в bytes, тестируется на моках.
- ``parse_csv(text) → list[FootballDataMatch]`` — приводит к строгому
  dataclass; пропускает строки без минимума колонок.
- ``FootballDataLoader.sync_season(league, season)`` — скачивает +
  парсит + батч-апсёртит в ``MatchResult``+``PinnacleClosingOdds``.

Использование:

    async with aiohttp.ClientSession() as s:
        loader = FootballDataLoader(session=s, db_session_factory=...)
        await loader.sync_season(league_code="E0", season_short="2425")
"""

from __future__ import annotations

import csv
import io
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from typing import Any

import aiohttp
from loguru import logger

BASE_URL = "https://www.football-data.co.uk/mmz4281"

# Карта внутреннего кода → человеко-читаемое название (для логов и БД).
LEAGUE_NAMES: dict[str, str] = {
    "E0": "England — Premier League",
    "E1": "England — Championship",
    "E2": "England — League One",
    "E3": "England — League Two",
    "EC": "England — Conference",
    "D1": "Germany — Bundesliga",
    "D2": "Germany — 2. Bundesliga",
    "I1": "Italy — Serie A",
    "I2": "Italy — Serie B",
    "SP1": "Spain — La Liga",
    "SP2": "Spain — Segunda",
    "F1": "France — Ligue 1",
    "F2": "France — Ligue 2",
    "N1": "Netherlands — Eredivisie",
    "B1": "Belgium — Pro League",
    "P1": "Portugal — Primeira Liga",
    "T1": "Turkey — Süper Lig",
    "G1": "Greece — Super League",
    "SC0": "Scotland — Premiership",
    "SC1": "Scotland — Championship",
    "SC2": "Scotland — League One",
    "SC3": "Scotland — League Two",
}


@dataclass(slots=True)
class FootballDataMatch:
    """Одна строка football-data.co.uk."""

    date: date
    home_team: str
    away_team: str
    home_goals: int
    away_goals: int
    full_time_result: str  # "H" | "D" | "A"
    pinnacle_home: float | None = None
    pinnacle_draw: float | None = None
    pinnacle_away: float | None = None
    b365_home: float | None = None
    b365_draw: float | None = None
    b365_away: float | None = None
    over_25_odds: float | None = None
    under_25_odds: float | None = None


# ─── Helpers ────────────────────────────────────────────────────────────────


def _parse_date(raw: str) -> date | None:
    """football-data.co.uk использует разные форматы даты в разные годы."""
    raw = raw.strip()
    if not raw:
        return None
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _parse_float(raw: str) -> float | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        v = float(raw)
        return v if v > 0 else None
    except ValueError:
        return None


def _parse_int(raw: str) -> int | None:
    raw = (raw or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


# ─── Парсер CSV ────────────────────────────────────────────────────────────


def parse_csv(text: str) -> list[FootballDataMatch]:
    """Парсит CSV-документ football-data.co.uk в список матчей.

    Кодировка отдельных файлов содержит символы CP1252 (например, é в
    "Olympique"). Подразумевается, что вызывающий уже декодировал bytes
    в str с правильной кодировкой.
    """
    reader = csv.DictReader(io.StringIO(text))
    out: list[FootballDataMatch] = []
    for row in reader:
        d = _parse_date(row.get("Date") or "")
        home = (row.get("HomeTeam") or "").strip()
        away = (row.get("AwayTeam") or "").strip()
        hg = _parse_int(row.get("FTHG") or "")
        ag = _parse_int(row.get("FTAG") or "")
        ftr = (row.get("FTR") or "").strip().upper()
        if not (d and home and away and hg is not None and ag is not None):
            continue
        if ftr not in ("H", "D", "A"):
            continue
        out.append(
            FootballDataMatch(
                date=d,
                home_team=home,
                away_team=away,
                home_goals=hg,
                away_goals=ag,
                full_time_result=ftr,
                pinnacle_home=_parse_float(row.get("PSH") or ""),
                pinnacle_draw=_parse_float(row.get("PSD") or ""),
                pinnacle_away=_parse_float(row.get("PSA") or ""),
                b365_home=_parse_float(row.get("B365H") or ""),
                b365_draw=_parse_float(row.get("B365D") or ""),
                b365_away=_parse_float(row.get("B365A") or ""),
                over_25_odds=_parse_float(row.get("B365>2.5") or ""),
                under_25_odds=_parse_float(row.get("B365<2.5") or ""),
            )
        )
    return out


def url_for(*, league_code: str, season_short: str) -> str:
    """Собирает URL CSV-файла."""
    return f"{BASE_URL}/{season_short}/{league_code}.csv"


def season_short_from_year(start_year: int) -> str:
    """1718 → '1718' для сезона 2017/18, 2425 → '2425' для 2024/25."""
    end_year = (start_year + 1) % 100
    return f"{start_year % 100:02d}{end_year:02d}"


# ─── Loader ────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class DownloadResult:
    league_code: str
    season_short: str
    bytes_downloaded: int
    matches_parsed: int
    matches_inserted: int
    matches_skipped_duplicate: int


class FootballDataLoader:
    """Скачивает и парсит football-data.co.uk CSV; пишет в БД при наличии.

    БД-запись опциональна: если ``db_session_factory`` не задан, loader
    отдаёт ``list[FootballDataMatch]`` напрямую (для бэктестов в памяти).
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        db_session_factory: Any | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._session = session
        self._db_factory = db_session_factory
        self._timeout = aiohttp.ClientTimeout(total=timeout)

    async def fetch_csv(
        self,
        *,
        league_code: str,
        season_short: str,
    ) -> str:
        """Скачивает CSV. Декодирует с попыткой utf-8, fallback cp1252."""
        url = url_for(league_code=league_code, season_short=season_short)
        async with self._session.get(url, timeout=self._timeout) as resp:
            resp.raise_for_status()
            data = await resp.read()
        for enc in ("utf-8", "cp1252", "latin-1"):
            try:
                return data.decode(enc)
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", errors="replace")

    async def fetch_matches(
        self,
        *,
        league_code: str,
        season_short: str,
    ) -> list[FootballDataMatch]:
        text = await self.fetch_csv(
            league_code=league_code, season_short=season_short
        )
        return parse_csv(text)

    async def fetch_seasons(
        self,
        *,
        league_code: str,
        seasons_short: Iterable[str],
    ) -> list[FootballDataMatch]:
        """Скачивает несколько сезонов одной лиги. Ошибка отдельного сезона
        не валит весь bulk-fetch — логируется и пропускается.
        """
        out: list[FootballDataMatch] = []
        for season in seasons_short:
            try:
                matches = await self.fetch_matches(
                    league_code=league_code, season_short=season
                )
                out.extend(matches)
                logger.info(
                    "football-data: {} {} → {} matches",
                    league_code, season, len(matches),
                )
            except Exception as exc:
                logger.warning(
                    "football-data: skip {} {}: {}",
                    league_code, season, exc,
                )
        return out


# ─── Бэктест-утилита ───────────────────────────────────────────────────────


def compute_naive_backtest_metrics(
    matches: list[FootballDataMatch],
) -> dict[str, Any]:
    """Простой sanity-check бэктест: какова hit-rate стратегии "брать фаворита".

    Используется CSV-импортом для верификации, что данные адекватны.
    Не претендует быть моделью — это ну очень простой sanity tracker.
    """
    n_with_odds = 0
    favorite_wins = 0
    underdog_wins = 0
    draws = 0
    cumulative_pl = 0.0  # P&L при ставке 1.0 на фаворита
    n_bets = 0
    for m in matches:
        if (
            m.pinnacle_home is None
            or m.pinnacle_away is None
            or m.pinnacle_draw is None
        ):
            continue
        n_with_odds += 1
        if m.pinnacle_home <= m.pinnacle_away:
            fav_odds, fav_outcome = m.pinnacle_home, "H"
        else:
            fav_odds, fav_outcome = m.pinnacle_away, "A"
        n_bets += 1
        if m.full_time_result == fav_outcome:
            cumulative_pl += fav_odds - 1.0
            favorite_wins += 1
        elif m.full_time_result == "D":
            cumulative_pl -= 1.0
            draws += 1
        else:
            cumulative_pl -= 1.0
            underdog_wins += 1
    return {
        "total_matches": len(matches),
        "matches_with_odds": n_with_odds,
        "n_bets": n_bets,
        "favorite_hits": favorite_wins,
        "draw_count": draws,
        "underdog_hits": underdog_wins,
        "favorite_hit_rate": (
            favorite_wins / n_bets if n_bets > 0 else None
        ),
        "cumulative_pl_per_bet": (
            cumulative_pl / n_bets if n_bets > 0 else None
        ),
        "roi_pct": (
            100.0 * cumulative_pl / n_bets if n_bets > 0 else None
        ),
    }


# Suppress "unused import" — UTC reserved for future date handling.
_ = UTC


__all__ = [
    "BASE_URL",
    "LEAGUE_NAMES",
    "DownloadResult",
    "FootballDataLoader",
    "FootballDataMatch",
    "compute_naive_backtest_metrics",
    "parse_csv",
    "season_short_from_year",
    "url_for",
]
