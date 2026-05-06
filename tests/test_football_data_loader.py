"""Тесты services/football_data_loader — парсер CSV + HTTP."""

from __future__ import annotations

from datetime import date
from typing import Any

import aiohttp
import pytest
from aiohttp import web

from services import football_data_loader as fdl

_SAMPLE_CSV = """\
Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR,B365H,B365D,B365A,PSH,PSD,PSA,B365>2.5,B365<2.5
E0,12/08/2023,Arsenal,Nottingham,2,1,H,1.30,5.50,9.00,1.31,5.65,9.20,1.50,2.55
E0,13/08/2023,Liverpool,Chelsea,1,1,D,1.85,3.80,3.90,1.87,3.85,3.95,1.65,2.30
E0,bad-date,X,Y,0,0,H,,,,,,,,
E0,20/08/2023,Empty,Goals,,,,1.50,3.50,4.00,,,,,
E0,21/08/2023,Brighton,Newcastle,3,1,H,2.40,3.30,2.85,2.45,3.40,2.90,1.85,2.05
"""


def test_parse_csv_skips_invalid_rows() -> None:
    matches = fdl.parse_csv(_SAMPLE_CSV)
    # 5 строк в CSV, но 2 невалидные (bad date + empty goals) → 3 матча.
    assert len(matches) == 3
    m1 = matches[0]
    assert m1.home_team == "Arsenal"
    assert m1.away_team == "Nottingham"
    assert m1.home_goals == 2
    assert m1.away_goals == 1
    assert m1.full_time_result == "H"
    assert m1.pinnacle_home == pytest.approx(1.31)
    assert m1.b365_home == pytest.approx(1.30)
    assert m1.over_25_odds == pytest.approx(1.50)


def test_parse_csv_handles_dd_mm_yyyy() -> None:
    matches = fdl.parse_csv(_SAMPLE_CSV)
    assert matches[0].date == date(2023, 8, 12)
    assert matches[1].date == date(2023, 8, 13)


def test_parse_csv_two_digit_year() -> None:
    csv_text = (
        "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n"
        "E0,15/03/12,A,B,1,0,H\n"
    )
    matches = fdl.parse_csv(csv_text)
    assert len(matches) == 1
    assert matches[0].date == date(2012, 3, 15)


def test_parse_csv_missing_odds_returns_none() -> None:
    csv_text = (
        "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n"
        "E0,01/01/2024,A,B,2,0,H\n"
    )
    matches = fdl.parse_csv(csv_text)
    assert len(matches) == 1
    assert matches[0].pinnacle_home is None
    assert matches[0].b365_home is None


def test_url_for() -> None:
    assert fdl.url_for(league_code="E0", season_short="2425") == (
        "https://www.football-data.co.uk/mmz4281/2425/E0.csv"
    )


def test_season_short_from_year() -> None:
    assert fdl.season_short_from_year(2024) == "2425"
    assert fdl.season_short_from_year(2018) == "1819"
    assert fdl.season_short_from_year(1999) == "9900"


def test_compute_naive_backtest() -> None:
    matches = fdl.parse_csv(_SAMPLE_CSV)
    result = fdl.compute_naive_backtest_metrics(matches)
    # Из 3 завершённых, у 3 есть Pinnacle odds.
    assert result["matches_with_odds"] == 3
    assert result["n_bets"] == 3
    assert result["favorite_hits"] == 2  # Arsenal H, Newcastle лучший fav…
    # Sanity: hit-rate в [0..1].
    assert 0 <= result["favorite_hit_rate"] <= 1


# ─── HTTP ───────────────────────────────────────────────────────────────────


@pytest.fixture
async def fake_fdc_server() -> Any:
    async def handler(request: web.Request) -> web.Response:
        league = request.match_info["league"]
        season = request.match_info["season"]
        if league == "E0.csv" and season == "2324":
            return web.Response(
                text=_SAMPLE_CSV,
                content_type="text/csv",
            )
        return web.Response(status=404)

    app = web.Application()
    app.router.add_get("/mmz4281/{season}/{league}", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
    base = f"http://127.0.0.1:{port}"
    try:
        yield base
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_loader_fetch_csv_text(
    monkeypatch: pytest.MonkeyPatch, fake_fdc_server: str
) -> None:
    monkeypatch.setattr(fdl, "BASE_URL", f"{fake_fdc_server}/mmz4281")
    async with aiohttp.ClientSession() as session:
        loader = fdl.FootballDataLoader(session=session)
        text = await loader.fetch_csv(league_code="E0", season_short="2324")
    assert "Arsenal" in text
    assert "Liverpool" in text


@pytest.mark.asyncio
async def test_loader_fetch_matches(
    monkeypatch: pytest.MonkeyPatch, fake_fdc_server: str
) -> None:
    monkeypatch.setattr(fdl, "BASE_URL", f"{fake_fdc_server}/mmz4281")
    async with aiohttp.ClientSession() as session:
        loader = fdl.FootballDataLoader(session=session)
        matches = await loader.fetch_matches(
            league_code="E0", season_short="2324"
        )
    assert len(matches) == 3
    assert matches[0].home_team == "Arsenal"


@pytest.mark.asyncio
async def test_loader_fetch_seasons_skips_404(
    monkeypatch: pytest.MonkeyPatch, fake_fdc_server: str
) -> None:
    """Если один сезон 404 — другие должны докачаться."""
    monkeypatch.setattr(fdl, "BASE_URL", f"{fake_fdc_server}/mmz4281")
    async with aiohttp.ClientSession() as session:
        loader = fdl.FootballDataLoader(session=session)
        matches = await loader.fetch_seasons(
            league_code="E0", seasons_short=["2324", "9999"]
        )
    assert len(matches) == 3  # только 2324 отдал данные
