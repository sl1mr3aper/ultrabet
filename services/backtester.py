"""Backtester — прогоняет исторические матчи через стратегию и считает P&L.

Использование:
    bt = Backtester(strategy=my_strat, bankroll=1000, stake_fn=flat_10)
    for historical_game in feed:
        bt.process(historical_game, market_coefs, result)
    print(bt.report())
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, datetime
from statistics import mean, pstdev


@dataclass(slots=True)
class HistoricalGame:
    game_id: int
    home_team: str
    away_team: str
    league: str
    starts_at: datetime
    home_score: int
    away_score: int


@dataclass(slots=True)
class Pick:
    game_id: int
    market: str
    probability: float
    odds: float
    fair_odds: float
    value_percent: float


@dataclass(slots=True)
class Placement:
    game_id: int
    market: str
    stake: float
    odds: float
    won: bool
    payout: float
    date: date


@dataclass(slots=True)
class BacktestReport:
    bets_placed: int
    bets_won: int
    bets_lost: int
    total_staked: float
    total_returned: float
    profit: float
    roi_pct: float
    hit_rate_pct: float
    max_drawdown: float
    best_day: float
    worst_day: float
    avg_odds: float
    avg_value_pct: float
    sharpe_like: float
    placements: list[Placement] = field(default_factory=list)


StrategyFn = Callable[[list[Pick]], list[Pick]]  # filter picks
StakeFn = Callable[[float, Pick], float]  # bankroll, pick → stake


def flat_stake(amount: float) -> StakeFn:
    return lambda _bankroll, _pick: amount


def percent_stake(pct: float) -> StakeFn:
    return lambda bankroll, _pick: bankroll * pct / 100.0


def kelly_stake(fraction: float = 1.0, *, cap: float = 0.10) -> StakeFn:
    def inner(bankroll: float, pick: Pick) -> float:
        b = pick.odds - 1.0
        p = pick.probability
        q = 1.0 - p
        f = (b * p - q) / b if b > 0 else 0.0
        f = max(0.0, min(cap, f * fraction))
        return bankroll * f
    return inner


@dataclass(slots=True)
class _PickHistoryEntry:
    """Буферная запись для последующего сброса в `match_pick_history`.

    Заполняется в `Backtester.process()` для КАЖДОГО матча — независимо
    от того, прошли пики стратегию или нет. Drainается асинхронным
    helper'ом `flush_history_to_db()` после прогона бэктеста.
    """

    game_id: int
    league_id: int | None
    league_name: str | None
    home_score: int
    away_score: int
    main_pick_market: str | None
    picks: list[Pick]


class Backtester:
    def __init__(
        self,
        *,
        strategy: StrategyFn,
        stake_fn: StakeFn,
        initial_bankroll: float = 1000.0,
    ) -> None:
        self._strategy = strategy
        self._stake_fn = stake_fn
        self._bankroll = initial_bankroll
        self._initial = initial_bankroll
        self._placements: list[Placement] = []
        self._peak_bankroll = initial_bankroll
        self._max_drawdown = 0.0
        self._daily_returns: dict[date, float] = {}
        # Буфер пиков для последующего сброса в БД.
        self._pick_history_buffer: list[_PickHistoryEntry] = []

    @property
    def pick_history_buffer(self) -> list[_PickHistoryEntry]:
        """Накопленные пики (для async-сброса в `match_pick_history`)."""
        return self._pick_history_buffer

    def process(
        self,
        game: HistoricalGame,
        picks: list[Pick],
        results_for_markets: dict[str, bool],
        *,
        league_id: int | None = None,
    ) -> int:
        # Главный пик = pick с максимальным composite score (если стратегия
        # отсортировала их). Если нет — берём первый (как fallback).
        main_pick_market: str | None = picks[0].market if picks else None
        # Буферим ВСЕ пики (а не только прошедшие стратегию), чтобы
        # secondary_pick_calibrator мог учесть и непокрытые рынки тоже.
        self._pick_history_buffer.append(
            _PickHistoryEntry(
                game_id=game.game_id,
                league_id=league_id,
                league_name=game.league,
                home_score=game.home_score,
                away_score=game.away_score,
                main_pick_market=main_pick_market,
                picks=list(picks),
            ),
        )

        selected = self._strategy(picks)
        placed = 0
        for pick in selected:
            if pick.market not in results_for_markets:
                continue
            stake = self._stake_fn(self._bankroll, pick)
            if stake <= 0 or stake > self._bankroll:
                continue
            self._bankroll -= stake
            won = results_for_markets[pick.market]
            payout = stake * pick.odds if won else 0.0
            self._bankroll += payout
            placement = Placement(
                game_id=game.game_id,
                market=pick.market,
                stake=stake,
                odds=pick.odds,
                won=won,
                payout=payout,
                date=game.starts_at.date(),
            )
            self._placements.append(placement)
            placed += 1
            if self._bankroll > self._peak_bankroll:
                self._peak_bankroll = self._bankroll
            dd = (self._peak_bankroll - self._bankroll) / self._peak_bankroll * 100.0
            if dd > self._max_drawdown:
                self._max_drawdown = dd
            d = game.starts_at.date()
            delta = payout - stake
            self._daily_returns[d] = self._daily_returns.get(d, 0.0) + delta
        return placed

    def report(self) -> BacktestReport:
        placements = self._placements
        bets_won = sum(1 for p in placements if p.won)
        bets_lost = sum(1 for p in placements if not p.won)
        total_staked = sum(p.stake for p in placements)
        total_returned = sum(p.payout for p in placements)
        profit = total_returned - total_staked
        roi = (profit / total_staked * 100.0) if total_staked > 0 else 0.0
        daily = list(self._daily_returns.values())
        best_day = max(daily) if daily else 0.0
        worst_day = min(daily) if daily else 0.0
        avg_odds = mean(p.odds for p in placements) if placements else 0.0
        avg_value = 0.0  # no access to value from placement, placeholder
        sharpe = 0.0
        if len(daily) > 1:
            avg_ret = mean(daily)
            std_ret = pstdev(daily)
            if std_ret > 0:
                sharpe = avg_ret / std_ret
        return BacktestReport(
            bets_placed=len(placements),
            bets_won=bets_won,
            bets_lost=bets_lost,
            total_staked=total_staked,
            total_returned=total_returned,
            profit=profit,
            roi_pct=roi,
            hit_rate_pct=(bets_won / len(placements) * 100.0) if placements else 0.0,
            max_drawdown=self._max_drawdown,
            best_day=best_day,
            worst_day=worst_day,
            avg_odds=avg_odds,
            avg_value_pct=avg_value,
            sharpe_like=sharpe,
            placements=list(placements),
        )

    @property
    def bankroll(self) -> float:
        return self._bankroll


async def flush_history_to_db(
    backtester: Backtester,
    session_factory: object,
) -> int:
    """Сбросить буфер пиков бэктестера в `match_pick_history`.

    Вызывается после `Backtester.process(...)` для каждого матча.
    Все записи помечены `is_backtest=True`, чтобы отделять их от
    live-прогнозов в калибраторе.
    """
    buf = backtester.pick_history_buffer
    if not buf:
        return 0
    from services.match_pick_history import (
        PickSnapshot,
        record_picks,
    )

    session = session_factory()  # type: ignore[operator,call-arg]
    written = 0
    try:
        for entry in buf:
            picks = [
                PickSnapshot(
                    market_key=p.market,
                    probability=p.probability,
                    fair_odds=p.fair_odds,
                )
                for p in entry.picks
            ]
            written += await record_picks(
                session,
                game_id=entry.game_id,
                league_id=entry.league_id,
                picks=picks,
                main_pick_key=entry.main_pick_market,
                is_backtest=True,
                home_score=entry.home_score,
                away_score=entry.away_score,
            )
        await session.commit()
    finally:
        await session.close()
    buf.clear()
    return written


__all__ = [
    "BacktestReport",
    "Backtester",
    "HistoricalGame",
    "Pick",
    "Placement",
    "flat_stake",
    "flush_history_to_db",
    "kelly_stake",
    "percent_stake",
]
