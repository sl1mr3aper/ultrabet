"""P0-10: бэктест-сервис для оценки модели на исторических данных.

Считает три ключевые метрики поверх ``prediction_outcomes``:

1. **Brier score** = mean((p − y)²) — calibration + sharpness в одном.
   Чем ниже — тем лучше; baseline 0.25 (рандом 50/50).

2. **ROI** = sum(profit_per_pick) / n_picks · 100% — чисто финансовая
   метрика. Берём пики, где наш ``predicted_probability × actual_odds > 1``
   (то есть EV+).

3. **CLV (avg)** = mean(prob × closing_odds − 1) — бьём ли мы closing
   line. >0 — модель устойчиво находит value перед закрытием рынка.

Сервис умеет фильтровать по league_id, market_category, временному
окну и группировать результаты. Используется как для оценки в реальном
времени (через /admin), так и для оффлайн-валидации.

Тесты — `tests/test_backtest_service.py`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import and_, select

from db.models import PredictionOutcome


@dataclass(slots=True)
class BacktestMetrics:
    """Агрегированные метрики бэктеста."""

    n_picks: int
    n_settled: int  # с известным hit
    n_with_odds: int  # с actual_odds (для ROI)
    n_with_close: int  # с closing_odds (для CLV)
    brier_score: float | None
    roi_pct: float | None  # %
    avg_clv: float | None
    positive_clv_rate: float | None  # доля пиков с CLV>0
    hit_rate: float | None  # доля сыгравших

    @property
    def is_empty(self) -> bool:
        return self.n_picks == 0


def _brier(prob: float, hit: bool) -> float:
    return (float(prob) - (1.0 if hit else 0.0)) ** 2


def _profit(prob: float, odds: float, hit: bool) -> float:
    """Profit per unit stake. EV+ только если prob*odds > 1."""
    if odds <= 1.0:
        return 0.0
    if hit:
        return float(odds) - 1.0
    return -1.0


class BacktestService:
    """Считает метрики поверх ``prediction_outcomes``.

    Параметры конструктора:
    - ``session_factory``: async фабрика SQLAlchemy сессий.
    """

    def __init__(self, *, session_factory: Any) -> None:
        self._session_factory = session_factory

    async def run(
        self,
        *,
        league_id: int | None = None,
        market_category: str | None = None,
        market_key: str | None = None,
        period_from: datetime | None = None,
        period_to: datetime | None = None,
        only_ev_plus: bool = True,
    ) -> BacktestMetrics:
        """Возвращает агрегированные метрики на выборке пиков.

        ``only_ev_plus=True`` — учитывает в ROI только те пики, где
        ``prob * actual_odds > 1`` (модель считала их value-ставками).
        """
        async with self._session_factory() as session:
            stmt = select(PredictionOutcome)
            cond = []
            if league_id is not None:
                cond.append(PredictionOutcome.league_id == league_id)
            if market_category is not None:
                cond.append(PredictionOutcome.market_category == market_category)
            if market_key is not None:
                cond.append(PredictionOutcome.market_key == market_key)
            if period_from is not None:
                cond.append(PredictionOutcome.created_at >= period_from)
            if period_to is not None:
                cond.append(PredictionOutcome.created_at <= period_to)
            if cond:
                stmt = stmt.where(and_(*cond))
            rows = (await session.execute(stmt)).scalars().all()

        return self._aggregate(rows, only_ev_plus=only_ev_plus)

    @staticmethod
    def _aggregate(
        rows: list[PredictionOutcome], *, only_ev_plus: bool
    ) -> BacktestMetrics:
        n_picks = len(rows)
        if n_picks == 0:
            return BacktestMetrics(
                n_picks=0,
                n_settled=0,
                n_with_odds=0,
                n_with_close=0,
                brier_score=None,
                roi_pct=None,
                avg_clv=None,
                positive_clv_rate=None,
                hit_rate=None,
            )

        brier_sum = 0.0
        n_brier = 0

        roi_profit = 0.0
        n_roi = 0

        clv_sum = 0.0
        n_clv = 0
        n_clv_pos = 0

        n_settled = 0
        n_hits = 0
        n_with_odds = 0
        n_with_close = 0

        for r in rows:
            prob = float(r.predicted_probability)
            hit = r.hit
            if hit is not None:
                n_settled += 1
                n_hits += int(bool(hit))
                brier_sum += _brier(prob, bool(hit))
                n_brier += 1

            odds = float(r.actual_odds) if r.actual_odds is not None else None
            if odds is not None and odds > 1.0:
                n_with_odds += 1
                # Берём в ROI только пики, где prob * odds > 1
                # (наша модель считала их EV+).
                if hit is not None and (not only_ev_plus or prob * odds > 1.0):
                    roi_profit += _profit(prob, odds, bool(hit))
                    n_roi += 1

            close = float(r.closing_odds) if r.closing_odds is not None else None
            if close is not None and close > 1.0:
                n_with_close += 1
                clv = prob * close - 1.0
                clv_sum += clv
                n_clv += 1
                if clv > 0.0:
                    n_clv_pos += 1

        brier = brier_sum / n_brier if n_brier > 0 else None
        roi = (roi_profit / n_roi) * 100.0 if n_roi > 0 else None
        clv_avg = clv_sum / n_clv if n_clv > 0 else None
        clv_pos_rate = n_clv_pos / n_clv if n_clv > 0 else None
        hit_rate = n_hits / n_settled if n_settled > 0 else None

        return BacktestMetrics(
            n_picks=n_picks,
            n_settled=n_settled,
            n_with_odds=n_with_odds,
            n_with_close=n_with_close,
            brier_score=brier,
            roi_pct=roi,
            avg_clv=clv_avg,
            positive_clv_rate=clv_pos_rate,
            hit_rate=hit_rate,
        )

    async def by_league(
        self,
        *,
        period_from: datetime | None = None,
        period_to: datetime | None = None,
        only_ev_plus: bool = True,
    ) -> dict[int, BacktestMetrics]:
        """Группирует пики по ``league_id`` и возвращает метрики по каждой."""
        async with self._session_factory() as session:
            stmt = select(PredictionOutcome).where(
                PredictionOutcome.league_id.is_not(None)
            )
            cond = []
            if period_from is not None:
                cond.append(PredictionOutcome.created_at >= period_from)
            if period_to is not None:
                cond.append(PredictionOutcome.created_at <= period_to)
            if cond:
                stmt = stmt.where(and_(*cond))
            rows = (await session.execute(stmt)).scalars().all()

        buckets: dict[int, list[PredictionOutcome]] = {}
        for r in rows:
            lid = int(r.league_id) if r.league_id is not None else 0
            buckets.setdefault(lid, []).append(r)

        return {
            lid: self._aggregate(rs, only_ev_plus=only_ev_plus)
            for lid, rs in buckets.items()
        }

    async def by_market(
        self,
        *,
        period_from: datetime | None = None,
        period_to: datetime | None = None,
        only_ev_plus: bool = True,
    ) -> dict[str, BacktestMetrics]:
        """Группирует пики по ``market_category`` (1×2/totals/btts/...)."""
        async with self._session_factory() as session:
            stmt = select(PredictionOutcome).where(
                PredictionOutcome.market_category.is_not(None)
            )
            cond = []
            if period_from is not None:
                cond.append(PredictionOutcome.created_at >= period_from)
            if period_to is not None:
                cond.append(PredictionOutcome.created_at <= period_to)
            if cond:
                stmt = stmt.where(and_(*cond))
            rows = (await session.execute(stmt)).scalars().all()

        buckets: dict[str, list[PredictionOutcome]] = {}
        for r in rows:
            cat = str(r.market_category or "")
            buckets.setdefault(cat, []).append(r)

        return {
            cat: self._aggregate(rs, only_ev_plus=only_ev_plus)
            for cat, rs in buckets.items()
        }


__all__ = [
    "BacktestMetrics",
    "BacktestService",
]
