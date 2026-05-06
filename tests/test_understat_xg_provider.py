"""Тесты services/understat_xg_provider — loader, provider, EWMA."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from db.models import Base, TeamXgSample
from services.understat_client import UnderstatMatch
from services.understat_xg_provider import (
    UnderstatXgLoader,
    UnderstatXgProvider,
    estimate_match_xg_from_avgs,
)


@pytest.fixture
async def session_factory() -> Any:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    @asynccontextmanager
    async def acquire() -> Any:
        async with factory() as s:
            yield s

    yield acquire
    await engine.dispose()


class _FakeUnderstatClient:
    def __init__(self, matches_by_league: dict[tuple[str, str], list[UnderstatMatch]]):
        self.matches = matches_by_league
        self.calls: list[tuple[str, str]] = []

    async def list_matches(self, league: str, season: str) -> list[UnderstatMatch]:
        self.calls.append((league, season))
        return list(self.matches.get((league, season), []))


def _mk_match(
    *,
    mid: int,
    home: str,
    away: str,
    home_xg: float,
    away_xg: float,
    finished: bool = True,
    dt: str | None = None,
) -> UnderstatMatch:
    return UnderstatMatch(
        match_id=mid,
        league="EPL",
        season="2025",
        datetime_utc=dt or "2026-04-30 18:00:00",
        home_team=home,
        away_team=away,
        home_goals=2 if finished else None,
        away_goals=1 if finished else None,
        home_xg=home_xg if finished else None,
        away_xg=away_xg if finished else None,
        is_finished=finished,
    )


# ─── Loader ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_loader_inserts_two_rows_per_match(session_factory: Any) -> None:
    matches = [
        _mk_match(mid=1, home="Arsenal", away="Chelsea", home_xg=1.5, away_xg=0.8),
        _mk_match(mid=2, home="Liverpool", away="Everton", home_xg=2.2, away_xg=0.4),
    ]
    client = _FakeUnderstatClient({("EPL", "2025"): matches})
    loader = UnderstatXgLoader(client=client, session_factory=session_factory)
    res = await loader.sync_league(league_slug="EPL", season="2025")
    assert res.fetched == 2
    assert res.inserted == 4

    # Повторный sync — дубли пропускаются (uq-индекс).
    res2 = await loader.sync_league(league_slug="EPL", season="2025")
    assert res2.inserted == 0
    assert res2.skipped == 4


@pytest.mark.asyncio
async def test_loader_skips_unfinished_matches(session_factory: Any) -> None:
    matches = [
        _mk_match(mid=1, home="A", away="B", home_xg=0, away_xg=0, finished=False),
        _mk_match(mid=2, home="C", away="D", home_xg=1.0, away_xg=0.5),
    ]
    client = _FakeUnderstatClient({("EPL", "2025"): matches})
    loader = UnderstatXgLoader(client=client, session_factory=session_factory)
    res = await loader.sync_league(league_slug="EPL", season="2025")
    assert res.fetched == 1  # только finished
    assert res.inserted == 2  # 2 строки для одного завершённого матча


@pytest.mark.asyncio
async def test_loader_unsupported_league_raises(session_factory: Any) -> None:
    client = _FakeUnderstatClient({})
    loader = UnderstatXgLoader(client=client, session_factory=session_factory)
    with pytest.raises(ValueError):
        await loader.sync_league(league_slug="NotALeague", season="2025")


# ─── Provider ──────────────────────────────────────────────────────────────


async def _seed_team_history(
    session_factory: Any,
    team_name: str,
    samples: list[tuple[float, float, datetime]],
    *,
    league_slug: str = "EPL",
) -> None:
    async with session_factory() as session:
        for i, (xg_for, xg_against, dt) in enumerate(samples):
            session.add(
                TeamXgSample(
                    source="understat",
                    league_slug=league_slug,
                    season="2025",
                    match_id=10_000 + i,
                    match_datetime=dt,
                    team_name=team_name,
                    is_home=True,
                    xg_for=xg_for,
                    xg_against=xg_against,
                    goals_for=int(xg_for),
                    goals_against=int(xg_against),
                )
            )
        await session.commit()


@pytest.mark.asyncio
async def test_provider_returns_none_when_no_data(session_factory: Any) -> None:
    p = UnderstatXgProvider(session_factory=session_factory)
    out = await p.get_team_averages(team_name="X")
    assert out is None


@pytest.mark.asyncio
async def test_provider_ewma_recent_weighted(session_factory: Any) -> None:
    base = datetime.now(tz=UTC)
    # 3 матча: давно 0.5, потом 0.5, потом недавний 3.0.
    # EWMA(α=0.65) должна быть ближе к 3.0 чем к 0.5.
    await _seed_team_history(
        session_factory,
        "TeamA",
        [
            (0.5, 1.0, base - timedelta(days=20)),
            (0.5, 1.0, base - timedelta(days=10)),
            (3.0, 0.3, base - timedelta(days=1)),
        ],
    )
    p = UnderstatXgProvider(session_factory=session_factory, ewma_alpha=0.65)
    out = await p.get_team_averages(team_name="TeamA")
    assert out is not None
    assert out.n_samples == 3
    assert out.xg_for_avg > 1.5  # ближе к 3, чем к 0.5
    assert out.xg_against_avg < 0.7


@pytest.mark.asyncio
async def test_provider_get_match_estimate(session_factory: Any) -> None:
    base = datetime.now(tz=UTC)
    # Сильная атака home (xg_for=2.0), слабая защита away (xg_against=2.0).
    # Ожидаемый home_xg ≈ (2.0 + 2.0) / 2 + 0.25 = 2.25.
    samples = [(2.0, 0.8, base - timedelta(days=i)) for i in range(5)]
    await _seed_team_history(session_factory, "Strong", samples)
    samples_weak = [(0.6, 2.0, base - timedelta(days=i)) for i in range(5)]
    await _seed_team_history(session_factory, "Weak", samples_weak)

    p = UnderstatXgProvider(session_factory=session_factory)
    est = await p.get_match_xg_estimate(home_team="Strong", away_team="Weak")
    assert est is not None
    home_xg, away_xg = est
    assert home_xg > away_xg  # home сильнее → больше xG
    assert 1.5 < home_xg < 3.0
    assert 0.2 < away_xg < 1.0


@pytest.mark.asyncio
async def test_provider_returns_none_below_min_samples(session_factory: Any) -> None:
    base = datetime.now(tz=UTC)
    # Меньше 3 матчей — Provider должен сказать "недоверительно".
    await _seed_team_history(
        session_factory,
        "NewTeam",
        [(1.0, 1.0, base - timedelta(days=2))],
    )
    await _seed_team_history(
        session_factory,
        "EnoughTeam",
        [(1.0, 1.0, base - timedelta(days=i)) for i in range(5)],
    )
    p = UnderstatXgProvider(session_factory=session_factory)
    out = await p.get_match_xg_estimate(home_team="NewTeam", away_team="EnoughTeam")
    assert out is None


# ─── Чистая функция ────────────────────────────────────────────────────────


def test_estimate_match_xg_basic() -> None:
    home, away = estimate_match_xg_from_avgs(
        home_for=2.0, home_against=1.0, away_for=1.0, away_against=2.0
    )
    # home_xg = (2.0 + 2.0)/2 + 0.25 = 2.25
    assert home == pytest.approx(2.25)
    # away_xg = (1.0 + 1.0)/2 - 0.25 = 0.75
    assert away == pytest.approx(0.75)


def test_estimate_match_xg_lower_bound() -> None:
    home, away = estimate_match_xg_from_avgs(
        home_for=0.0, home_against=0.0, away_for=0.0, away_against=0.0,
        home_advantage_goals=0.0,
    )
    assert home == 0.2 and away == 0.2  # пол ограничен 0.2
