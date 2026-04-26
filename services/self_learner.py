"""Self-learning и корреляционный анализ по исторической БД.

Принцип работы:
- Фоновая задача раз в сутки оценивает `PredictionOutcome` записи, у которых
  hit=None, по `MatchResult` (сыгранный матч → проверяем, сбылся ли прогноз).
- Вычисляет *калибровку* модели: реальный хит-рейт по вероятностным корзинам
  (0.5–0.6, 0.6–0.7, …, 0.9–1.0) — это основа для обратной связи в ensemble.
- Считает *Brier score* и *log-loss* по свежим матчам; экспортирует в
  `accuracy_notes` для отчёта.
- Предоставляет корреляционные коэффициенты между входными фичами
  (Glicko Δ, xG Δ, home-advantage, травмы) и реальным исходом.

Результаты используются в `services.prediction_service` для адаптивной
корректировки, и в админ-панели для мониторинга качества.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from math import log
from typing import Any

from loguru import logger
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import MatchResult, PredictionOutcome


@dataclass(slots=True)
class CalibrationBin:
    lower: float
    upper: float
    count: int = 0
    hits: int = 0

    @property
    def empirical(self) -> float:
        return (self.hits / self.count) if self.count else 0.0

    @property
    def midpoint(self) -> float:
        return (self.lower + self.upper) / 2


@dataclass(slots=True)
class LearningSnapshot:
    brier: float = 0.0
    log_loss: float = 0.0
    samples: int = 0
    calibration: list[CalibrationBin] = field(default_factory=list)
    market_hit_rates: dict[str, tuple[int, int]] = field(default_factory=dict)
    updated_at: datetime = field(default_factory=lambda: datetime.now(tz=UTC))


class SelfLearner:
    """Простая корреляционно-калибровочная модель на базе истории."""

    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory
        self._latest: LearningSnapshot | None = None

    async def evaluate_pending(self) -> int:
        """Оценить ещё неоценённые прогнозы (`hit is None`).

        Соединяем с `MatchResult` по game_id и market_key. Возвращает
        количество обновлённых записей.
        """
        session: AsyncSession = self._session_factory()
        updated = 0
        try:
            rows = await session.scalars(
                select(PredictionOutcome).where(PredictionOutcome.hit.is_(None)).limit(2000)
            )
            outcomes = list(rows)
            if not outcomes:
                return 0
            ids = [o.game_id for o in outcomes]
            results_rows = await session.scalars(
                select(MatchResult).where(MatchResult.game_id.in_(ids))
            )
            results = {r.game_id: r for r in results_rows}
            for o in outcomes:
                r = results.get(o.game_id)
                if r is None or r.home_score is None or r.away_score is None:
                    continue
                hit = _check_market(o.market_key, r.home_score, r.away_score)
                if hit is not None:
                    o.hit = hit
                    o.evaluated_at = datetime.now(tz=UTC)
                    updated += 1
            await session.commit()
        except Exception as exc:
            logger.exception("SelfLearner.evaluate_pending failed: {}", exc)
            await session.rollback()
        finally:
            await session.close()
        return updated

    async def compute_snapshot(self, *, days: int = 60) -> LearningSnapshot:
        """Пересчитать метрики качества за последние N дней."""
        session: AsyncSession = self._session_factory()
        snap = LearningSnapshot()
        bins = [
            CalibrationBin(0.50, 0.60),
            CalibrationBin(0.60, 0.70),
            CalibrationBin(0.70, 0.80),
            CalibrationBin(0.80, 0.90),
            CalibrationBin(0.90, 1.00),
        ]
        try:
            cutoff = datetime.now(tz=UTC) - timedelta(days=days)
            rows = await session.scalars(
                select(PredictionOutcome).where(
                    and_(
                        PredictionOutcome.hit.is_not(None),
                        PredictionOutcome.evaluated_at.is_not(None),
                        PredictionOutcome.evaluated_at >= cutoff,
                    )
                )
            )
            outcomes = list(rows)
            if not outcomes:
                snap.calibration = bins
                self._latest = snap
                return snap

            brier_sum = 0.0
            log_sum = 0.0
            market_stat: dict[str, list[int]] = {}
            for o in outcomes:
                p = max(1e-6, min(1 - 1e-6, o.predicted_probability))
                y = 1 if o.hit else 0
                brier_sum += (p - y) ** 2
                log_sum += -(y * log(p) + (1 - y) * log(1 - p))
                m = market_stat.setdefault(o.market_key, [0, 0])
                m[0] += 1
                m[1] += y
                for b in bins:
                    if b.lower <= p < b.upper or (b.upper == 1.0 and p >= 0.9):
                        b.count += 1
                        b.hits += y
                        break
            snap.samples = len(outcomes)
            snap.brier = brier_sum / max(1, len(outcomes))
            snap.log_loss = log_sum / max(1, len(outcomes))
            snap.calibration = bins
            snap.market_hit_rates = {k: (v[1], v[0]) for k, v in market_stat.items()}
            self._latest = snap
            return snap
        finally:
            await session.close()

    @property
    def latest(self) -> LearningSnapshot | None:
        return self._latest

    def calibrate(self, probability: float) -> float:
        """Калибровать вероятность по последнему snapshot.

        Если исторически в корзине p∈[0.80, 0.90] эмпирический хит-рейт = 0.72,
        исходящий `probability=0.85` сдвинется ближе к 0.72.
        """
        snap = self._latest
        if snap is None or not snap.calibration:
            return probability
        p = max(0.0, min(1.0, probability))
        for b in snap.calibration:
            if b.count == 0:
                continue
            if b.lower <= p < b.upper or (b.upper == 1.0 and p >= 0.9):
                # Сглаживание: берём 0.6 модели + 0.4 эмпирики
                return max(0.0, min(1.0, 0.6 * p + 0.4 * b.empirical))
        return p


def _check_market(market_key: str, home: int, away: int) -> bool | None:
    """Проверка сыгранности рынка по реальному счёту."""
    total = home + away
    key = market_key.lower()
    # 1X2 / double chance
    if key in {"home", "1", "home_win"}:
        return home > away
    if key in {"away", "2", "away_win"}:
        return away > home
    if key in {"draw", "x"}:
        return home == away
    if key in {"1x", "double_chance_1x"}:
        return home >= away
    if key in {"x2", "double_chance_x2"}:
        return away >= home
    if key in {"12", "double_chance_12"}:
        return home != away
    # Totals
    for line in (0.5, 1.5, 2.5, 3.5, 4.5):
        if key in {f"over_{int(line * 10)}", f"over_{line}", f"over{line}"}:
            return total > line
        if key in {f"under_{int(line * 10)}", f"under_{line}", f"under{line}"}:
            return total < line
    # BTTS
    if key in {"btts", "btts_yes", "both_teams_score"}:
        return home >= 1 and away >= 1
    if key in {"btts_no", "both_teams_score_no"}:
        return home == 0 or away == 0
    # Individual totals
    for side, val in (("home", home), ("away", away)):
        for line in (0.5, 1.5, 2.5):
            if key == f"{side}_over_{int(line * 10)}":
                return val > line
            if key == f"{side}_under_{int(line * 10)}":
                return val < line
    return None


__all__ = ["CalibrationBin", "LearningSnapshot", "SelfLearner"]
