"""Тесты SecondaryPickCalibrator + match_pick_history записи.

Проверяем что:
  * `record_picks` пишет в БД и UPSERT'ит без дубликатов;
  * `resolve_pending_picks` ставит hit + main_pick_hit;
  * `compute_adjustments` рассчитывает factor по эмпирике;
  * pick_adjustment_cache отдаёт корректные factor'ы.
"""

from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from db.models import (
    Base,
    MatchPickHistory,
    MatchResult,
    PickAdjustment,
)
from services.match_pick_history import (
    PickSnapshot,
    record_picks,
    resolve_pending_picks,
)
from services.secondary_pick_calibrator import (
    SecondaryPickCalibrator,
    _factor,
)


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    yield factory
    await engine.dispose()


@pytest.mark.asyncio
async def test_record_picks_writes_all_markets(session_factory) -> None:
    """record_picks пишет каждый pick в `match_pick_history`."""
    session = session_factory()
    try:
        n = await record_picks(
            session,
            game_id=1001,
            league_id=42,
            picks=[
                PickSnapshot(market_key="home", probability=0.55, fair_odds=1.82),
                PickSnapshot(market_key="btts", probability=0.62, fair_odds=1.61),
                PickSnapshot(market_key="o25", probability=0.48),
            ],
            main_pick_key="btts",
            is_backtest=False,
        )
        await session.commit()
        assert n == 3
        from sqlalchemy import select
        rows = list((await session.scalars(select(MatchPickHistory))).all())
        assert len(rows) == 3
        main = next(r for r in rows if r.market_key == "btts")
        assert main.is_main_pick is True
        non_main = next(r for r in rows if r.market_key == "home")
        assert non_main.is_main_pick is False
        assert non_main.predicted_probability == pytest.approx(0.55)
        assert non_main.fair_odds == pytest.approx(1.82)
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_record_picks_upsert_no_duplicates(session_factory) -> None:
    """Повторный record_picks обновляет, не дублирует."""
    session = session_factory()
    try:
        await record_picks(
            session,
            game_id=1002,
            league_id=42,
            picks=[PickSnapshot(market_key="home", probability=0.50)],
            main_pick_key=None,
        )
        await session.commit()
        await record_picks(
            session,
            game_id=1002,
            league_id=42,
            picks=[PickSnapshot(market_key="home", probability=0.65)],
            main_pick_key=None,
        )
        await session.commit()
        from sqlalchemy import select
        rows = list((await session.scalars(select(MatchPickHistory))).all())
        assert len(rows) == 1
        assert rows[0].predicted_probability == pytest.approx(0.65)
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_resolve_pending_picks_sets_hit_and_main_flag(session_factory) -> None:
    """После resolve_pending_picks hit и main_pick_hit заполнены."""
    session = session_factory()
    try:
        # 1) MatchResult: счёт 2:1.
        session.add(
            MatchResult(
                game_id=2001,
                league_id=10,
                home_score=2,
                away_score=1,
            ),
        )
        # 2) Пики: главный = home (зайдёт), вторичный = over_2.5 (зайдёт)
        await record_picks(
            session,
            game_id=2001,
            league_id=10,
            picks=[
                PickSnapshot(market_key="home", probability=0.6),
                PickSnapshot(market_key="over_2.5", probability=0.5),
                PickSnapshot(market_key="btts", probability=0.7),
            ],
            main_pick_key="home",
        )
        await session.commit()
    finally:
        await session.close()

    n = await resolve_pending_picks(session_factory)
    assert n >= 3

    session = session_factory()
    try:
        from sqlalchemy import select
        rows = list((await session.scalars(select(MatchPickHistory))).all())
        by_key = {r.market_key: r for r in rows}
        assert by_key["home"].hit is True
        assert by_key["over_2.5"].hit is True
        assert by_key["btts"].hit is True
        # main_pick_hit для всех = True (главный зашёл)
        for r in rows:
            assert r.main_pick_hit is True
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_compute_adjustments_inserts_into_pick_adjustments(
    session_factory,
) -> None:
    """compute_adjustments сохраняет PickAdjustment если N >= MIN_SAMPLES."""
    # Подсунем 30 пиков по market="btts" с empirical=0.7 и predicted=0.5
    session = session_factory()
    try:
        for i in range(30):
            session.add(
                MatchPickHistory(
                    game_id=10000 + i,
                    league_id=1,
                    market_key="btts",
                    market_category="btts",
                    predicted_probability=0.5,
                    is_main_pick=False,
                    is_backtest=False,
                    hit=(i < 21),  # 21/30 = 70% empirical
                ),
            )
        await session.commit()
    finally:
        await session.close()

    calib = SecondaryPickCalibrator(session_factory)
    stats = await calib.compute_adjustments()
    # one stat for "btts", condition="any"
    btts = [s for s in stats if s.market_key == "btts" and s.condition == "any"]
    assert len(btts) == 1
    s = btts[0]
    assert s.sample_size == 30
    assert s.empirical_hit_rate == pytest.approx(0.7)
    assert s.avg_predicted_prob == pytest.approx(0.5)
    # factor = 0.7 / 0.5 = 1.4
    assert s.adjustment_factor == pytest.approx(1.4)
    # Проверяем, что PickAdjustment сохранён в БД
    session = session_factory()
    try:
        from sqlalchemy import select
        adj = list((await session.scalars(select(PickAdjustment))).all())
        # one row btts/any
        btts_rows = [a for a in adj if a.market_key == "btts"]
        assert len(btts_rows) == 1
        assert btts_rows[0].adjustment_factor == pytest.approx(1.4)
    finally:
        await session.close()


@pytest.mark.asyncio
async def test_compute_adjustments_skips_under_min_samples(
    session_factory,
) -> None:
    """Если N < MIN_SAMPLES (30), adjustment не создаётся."""
    session = session_factory()
    try:
        for i in range(10):  # only 10
            session.add(
                MatchPickHistory(
                    game_id=20000 + i,
                    market_key="home",
                    market_category="1x2",
                    predicted_probability=0.5,
                    is_main_pick=False,
                    is_backtest=False,
                    hit=True,
                ),
            )
        await session.commit()
    finally:
        await session.close()
    calib = SecondaryPickCalibrator(session_factory)
    stats = await calib.compute_adjustments()
    assert all(s.market_key != "home" for s in stats)


def test_factor_clipped_to_min_max() -> None:
    """factor() зажимает результат в [MIN_FACTOR, MAX_FACTOR]."""
    # Огромная переоценка (empirical=0.9, predicted=0.3) → raw=3.0 → clip 1.5
    assert _factor(0.9, 0.3) == pytest.approx(1.5)
    # Огромная недооценка (empirical=0.1, predicted=0.6) → raw=0.16 → clip 0.5
    assert _factor(0.1, 0.6) == pytest.approx(0.5)
    # avg_pred ≈ 0 → factor=1.0 (защита от деления на 0)
    assert _factor(0.5, 0.0) == 1.0
    assert _factor(0.5, 0.005) == 1.0
    # Нормальный случай: empirical=0.55, predicted=0.5 → factor=1.1
    assert _factor(0.55, 0.5) == pytest.approx(1.1)


@pytest.mark.asyncio
async def test_get_adjustments_returns_dict(session_factory) -> None:
    """get_adjustments вернёт {market: factor} для условия."""
    session = session_factory()
    try:
        session.add(
            PickAdjustment(
                market_key="btts",
                condition="any",
                sample_size=50,
                empirical_hit_rate=0.6,
                avg_predicted_prob=0.5,
                adjustment_factor=1.2,
                confidence=0.25,
            ),
        )
        session.add(
            PickAdjustment(
                market_key="btts",
                condition="main_lost",
                sample_size=30,
                empirical_hit_rate=0.65,
                avg_predicted_prob=0.5,
                adjustment_factor=1.3,
                confidence=0.15,
            ),
        )
        await session.commit()
    finally:
        await session.close()
    calib = SecondaryPickCalibrator(session_factory)
    any_map = await calib.get_adjustments(condition="any")
    assert any_map.get("btts") == pytest.approx(1.2)
    main_lost_map = await calib.get_adjustments(condition="main_lost")
    assert main_lost_map.get("btts") == pytest.approx(1.3)
