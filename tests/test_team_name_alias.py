"""Тесты services.team_name_alias — нормализация и кросс-источный маппинг."""

from __future__ import annotations

import pytest

from services.team_name_alias import (
    league_to_fdc_code,
    league_to_understat_slug,
    normalize,
    to_fdc,
    to_understat,
)


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("Manchester United", "manchesterunited"),
        ("Man United", "manunited"),
        ("FC Bayern München", "bayernmunchen"),
        ("Atlético de Madrid", "atleticodemadrid"),
        ("Paris SG", "parissg"),
        ("Paris Saint Germain", "parissaintgermain"),
        ("Internazionale", "internazionale"),
        ("Inter", "inter"),
        ("FC", ""),  # лишь префикс
        ("", ""),
    ],
)
def test_normalize(raw: str, expected: str) -> None:
    assert normalize(raw) == expected


@pytest.mark.parametrize(
    "sstats,understat",
    [
        ("Manchester United", "Manchester United"),
        ("Tottenham Hotspur", "Tottenham"),
        ("Wolverhampton Wanderers", "Wolverhampton Wanderers"),
        ("FC Bayern München", "Bayern Munich"),
        ("Atletico Madrid", "Atletico Madrid"),
        ("Paris Saint-Germain", "Paris Saint Germain"),
        ("Olympique de Marseille", "Marseille"),
        ("Internazionale", "Internazionale"),
    ],
)
def test_to_understat_known_clubs(sstats: str, understat: str) -> None:
    assert to_understat(sstats) == understat


def test_to_understat_unknown_returns_input() -> None:
    assert to_understat("Random FC") == "Random FC"
    assert to_understat("") == ""


@pytest.mark.parametrize(
    "sstats,fdc",
    [
        ("Manchester United", "Man United"),
        ("Manchester City", "Man City"),
        ("Wolverhampton Wanderers", "Wolves"),
        ("Brighton & Hove Albion", "Brighton"),
        ("Atletico Madrid", "Ath Madrid"),
        ("Athletic Bilbao", "Ath Bilbao"),
        ("Paris Saint-Germain", "Paris SG"),
        ("Borussia Mönchengladbach", "M'gladbach"),
        ("Internazionale", "Inter"),
        ("Nottingham Forest", "Nott'm Forest"),
    ],
)
def test_to_fdc_known_clubs(sstats: str, fdc: str) -> None:
    assert to_fdc(sstats) == fdc


def test_to_fdc_unknown_returns_input() -> None:
    assert to_fdc("Random FC") == "Random FC"
    assert to_fdc("") == ""


@pytest.mark.parametrize(
    "league,slug",
    [
        ("Premier League", "EPL"),
        ("La Liga", "La_liga"),
        ("LaLiga", "La_liga"),
        ("Bundesliga", "Bundesliga"),
        ("Serie A", "Serie_A"),
        ("Ligue 1", "Ligue_1"),
        ("Russian Premier League", "RFPL"),
        ("RPL", "RFPL"),
        ("League 2 Saudi Arabia", None),
        ("", None),
    ],
)
def test_league_to_understat_slug(league: str, slug: str | None) -> None:
    assert league_to_understat_slug(league) == slug


@pytest.mark.parametrize(
    "league,code",
    [
        ("Premier League", "E0"),
        ("Championship", "E1"),
        ("La Liga", "SP1"),
        ("Bundesliga", "D1"),
        ("2. Bundesliga", "D2"),
        ("Serie A", "I1"),
        ("Ligue 1", "F1"),
        ("Eredivisie", "N1"),
        ("Random League", None),
        ("", None),
    ],
)
def test_league_to_fdc_code(league: str, code: str | None) -> None:
    assert league_to_fdc_code(league) == code


def test_normalize_handles_diacritics_and_apostrophes() -> None:
    # Реальные имена с французскими/немецкими/португальскими буквами
    assert normalize("Saint-Étienne") == "saintetienne"
    assert normalize("São Paulo") == "saopaulo"
    assert normalize("M'gladbach") == "mgladbach"
