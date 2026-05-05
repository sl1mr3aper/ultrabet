"""Калибратор вторичных пиков на основе истории `match_pick_history`.

Идея (запрос пользователя): когда главный прогноз матча НЕ зашёл, но
другие пики при этом счёте зашли, мы должны учитывать их статистику
отдельно. Если эмпирически рынок зашёл при провале главного значимо
чаще, чем модель ожидала, поднимаем его коэффициент доверия.

Алгоритм:
  1. Группируем пики (`match_pick_history`) по `market_key` и
     `condition` ∈ {"any", "main_lost", "main_won"}.
  2. Для каждой группы (где >= MIN_SAMPLES):
       empirical = sum(hit) / count
       avg_pred  = mean(predicted_probability)
       factor    = clip(empirical / avg_pred, 0.5, 1.5)
       confidence = min(1.0, count / 200)
  3. Сохраняем в `pick_adjustments` (UPSERT).

Применение в `value_engine.score_pick`:
  * Если есть запись `(market_key, "any")` — применяем.
  * Если есть `(market_key, "main_lost")` И мы прогнозируем рынок
    как «вторичный» — поднимаем приоритет.

Запускается ежедневным cron'ом (вместе с self_learner).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from loguru import logger
from sqlalchemy import and_, func, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import MatchPickHistory, PickAdjustment

# Минимальное число резолвнутых пиков, чтобы делать adjustment.
# 30 — стандартный порог self_learner (тоже в этом проекте).
MIN_SAMPLES = 30
# Жёсткие границы adjustment_factor — никакой рынок не может быть
# поднят/опущен сильнее чем в 1.5x / 0.5x относительно сырой модели.
MIN_FACTOR = 0.5
MAX_FACTOR = 1.5


@dataclass(slots=True, frozen=True)
class CalibrationStats:
    market_key: str
    condition: str
    sample_size: int
    empirical_hit_rate: float
    avg_predicted_prob: float
    adjustment_factor: float
    confidence: float


def _condition(main_pick_hit: bool | None) -> str:
    """Маппинг булевого main_pick_hit в текстовое условие."""
    if main_pick_hit is None:
        return "any"  # main_pick_hit ещё не известен — считаем «без условия»
    return "main_won" if main_pick_hit else "main_lost"


def _factor(empirical: float, avg_pred: float) -> float:
    """Adjustment factor с safe-fallback и зажатием в [MIN, MAX]."""
    if avg_pred <= 0.01:
        return 1.0
    raw = empirical / avg_pred
    return max(MIN_FACTOR, min(MAX_FACTOR, raw))


class SecondaryPickCalibrator:
    """Считает adjustment_factor по истории всех пиков."""

    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory

    async def compute_adjustments(
        self, *, only_resolved: bool = True,
    ) -> list[CalibrationStats]:
        """Пересчитать adjustment_factor по всем market_key."""
        session: AsyncSession = self._session_factory()
        try:
            # 1) Без условия: market_key → (count, sum(hit), avg(prob))
            base_q = (
                select(
                    MatchPickHistory.market_key,
                    func.count().label("n"),
                    func.sum(
                        # SQLite-friendly: cast bool to int
                        func.coalesce(
                            func.iif(
                                MatchPickHistory.hit.is_(True), 1, 0,
                            ), 0,
                        ),
                    ).label("hits"),
                    func.avg(
                        MatchPickHistory.predicted_probability,
                    ).label("avg_p"),
                )
                .where(MatchPickHistory.hit.is_not(None))
                .group_by(MatchPickHistory.market_key)
            )
            # 2) С условием main_pick_hit: разделяем на main_won / main_lost
            cond_q = (
                select(
                    MatchPickHistory.market_key,
                    MatchPickHistory.main_pick_hit,
                    func.count().label("n"),
                    func.sum(
                        func.coalesce(
                            func.iif(
                                MatchPickHistory.hit.is_(True), 1, 0,
                            ), 0,
                        ),
                    ).label("hits"),
                    func.avg(
                        MatchPickHistory.predicted_probability,
                    ).label("avg_p"),
                )
                .where(
                    and_(
                        MatchPickHistory.hit.is_not(None),
                        MatchPickHistory.main_pick_hit.is_not(None),
                        MatchPickHistory.is_main_pick.is_(False),
                    ),
                )
                .group_by(
                    MatchPickHistory.market_key,
                    MatchPickHistory.main_pick_hit,
                )
            )

            base_rows = (await session.execute(base_q)).all()
            cond_rows = (await session.execute(cond_q)).all()

            stats: list[CalibrationStats] = []
            for r in base_rows:
                n = int(r.n or 0)
                if n < MIN_SAMPLES:
                    continue
                hits = int(r.hits or 0)
                avg_p = float(r.avg_p or 0.0)
                emp = hits / n if n > 0 else 0.0
                stats.append(
                    CalibrationStats(
                        market_key=r.market_key,
                        condition="any",
                        sample_size=n,
                        empirical_hit_rate=emp,
                        avg_predicted_prob=avg_p,
                        adjustment_factor=_factor(emp, avg_p),
                        confidence=min(1.0, n / 200.0),
                    ),
                )
            for r in cond_rows:
                n = int(r.n or 0)
                if n < MIN_SAMPLES:
                    continue
                hits = int(r.hits or 0)
                avg_p = float(r.avg_p or 0.0)
                emp = hits / n if n > 0 else 0.0
                stats.append(
                    CalibrationStats(
                        market_key=r.market_key,
                        condition=_condition(bool(r.main_pick_hit)),
                        sample_size=n,
                        empirical_hit_rate=emp,
                        avg_predicted_prob=avg_p,
                        adjustment_factor=_factor(emp, avg_p),
                        confidence=min(1.0, n / 200.0),
                    ),
                )

            # Сохраняем
            for s in stats:
                stmt = sqlite_insert(PickAdjustment).values(
                    market_key=s.market_key,
                    condition=s.condition,
                    sample_size=s.sample_size,
                    empirical_hit_rate=s.empirical_hit_rate,
                    avg_predicted_prob=s.avg_predicted_prob,
                    adjustment_factor=s.adjustment_factor,
                    confidence=s.confidence,
                    updated_at=datetime.now(tz=UTC),
                ).on_conflict_do_update(
                    index_elements=["market_key", "condition"],
                    set_={
                        "sample_size": s.sample_size,
                        "empirical_hit_rate": s.empirical_hit_rate,
                        "avg_predicted_prob": s.avg_predicted_prob,
                        "adjustment_factor": s.adjustment_factor,
                        "confidence": s.confidence,
                        "updated_at": datetime.now(tz=UTC),
                    },
                )
                await session.execute(stmt)
            await session.commit()
            logger.info(
                "SecondaryPickCalibrator: updated {} adjustments",
                len(stats),
            )
            return stats
        except Exception as exc:
            logger.exception(
                "SecondaryPickCalibrator failed: {}", exc,
            )
            await session.rollback()
            return []
        finally:
            await session.close()

    async def get_adjustments(
        self, *, condition: str = "any",
    ) -> dict[str, float]:
        """Вернуть {market_key: factor} для применения в value_engine."""
        session: AsyncSession = self._session_factory()
        try:
            rows = await session.scalars(
                select(PickAdjustment).where(
                    PickAdjustment.condition == condition,
                ),
            )
            return {
                a.market_key: float(a.adjustment_factor) for a in rows
            }
        except Exception as exc:
            logger.debug("get_adjustments failed: {}", exc)
            return {}
        finally:
            await session.close()


__all__ = [
    "MAX_FACTOR",
    "MIN_FACTOR",
    "MIN_SAMPLES",
    "CalibrationStats",
    "SecondaryPickCalibrator",
]
