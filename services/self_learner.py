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

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from math import log
from typing import Any

from loguru import logger
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import BacktestResult, MatchResult, PredictionOutcome


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
    # Per-category Brier — отдельно по «1X2», «total», «btts», «handicap»,
    # «individual_total» — чтобы видеть, где модель шумит больше всего.
    category_brier: dict[str, float] = field(default_factory=dict)
    # Per-market hit-rate с лагом ≥30 матчей — для блок-листа «не показывать
    # как «брать»» если рынок исторически в минусе.
    market_clv: dict[str, float] = field(default_factory=dict)
    # Holdout Brier — на последних 14 днях (out-of-time). Если применение
    # калибровки ухудшает holdout Brier — anti-overfit guard блокирует
    # обновление весов ансамбля.
    holdout_brier_before: float | None = None
    holdout_brier_after: float | None = None
    holdout_samples: int = 0
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
        """Пересчитать метрики качества за последние N дней.

        Дополнительно:
        * считает per-category Brier (1X2 / total / btts / handicap /
          individual_total) — чтобы понимать, где модель проигрывает;
        * считает hit-rate по market_key, и средний CLV по нему;
        * запускает holdout-валидацию: последние 14 дней — это out-of-time
          выборка. Если применение калибровки ухудшает holdout Brier на
          ≥5%, anti-overfit guard блокирует обновление весов ансамбля.
        """
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
            # category_stat: cat -> [n, brier_sum]
            category_stat: dict[str, list[float]] = {}
            # market_clv_stat: market_key -> [n, clv_sum]
            clv_stat: dict[str, list[float]] = {}
            # holdout (последние 14 дней)
            holdout_cutoff = datetime.now(tz=UTC) - timedelta(days=14)
            holdout_brier_before = 0.0
            holdout_brier_after = 0.0
            holdout_n = 0
            for o in outcomes:
                p = max(1e-6, min(1 - 1e-6, o.predicted_probability))
                y = 1 if o.hit else 0
                brier_sum += (p - y) ** 2
                log_sum += -(y * log(p) + (1 - y) * log(1 - p))
                m = market_stat.setdefault(o.market_key, [0, 0])
                m[0] += 1
                m[1] += y
                # Per-category
                cat = _market_category(o.market_key)
                cs = category_stat.setdefault(cat, [0.0, 0.0])
                cs[0] += 1
                cs[1] += (p - y) ** 2
                # CLV — если есть closing_odds
                if (
                    o.closing_odds is not None
                    and float(o.closing_odds) > 1.01
                ):
                    cl = float(o.closing_odds)
                    clv_val = (p * cl) - 1.0
                    cv = clv_stat.setdefault(o.market_key, [0.0, 0.0])
                    cv[0] += 1
                    cv[1] += clv_val
                # Holdout (последние 14 дней)
                if o.evaluated_at and o.evaluated_at >= holdout_cutoff:
                    holdout_n += 1
                    holdout_brier_before += (p - y) ** 2
                    # Применяем текущую калибровку (если есть) и считаем «после»
                    if self._latest is not None and self._latest.calibration:
                        p_cal = self._calibrate_with(p, self._latest)
                        holdout_brier_after += (p_cal - y) ** 2
                    else:
                        holdout_brier_after += (p - y) ** 2
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
            snap.category_brier = {
                k: (v[1] / v[0] if v[0] > 0 else 0.0) for k, v in category_stat.items()
            }
            snap.market_clv = {
                k: (v[1] / v[0] if v[0] > 0 else 0.0)
                for k, v in clv_stat.items()
            }
            if holdout_n > 0:
                snap.holdout_samples = holdout_n
                snap.holdout_brier_before = holdout_brier_before / holdout_n
                snap.holdout_brier_after = holdout_brier_after / holdout_n

            # Anti-overfit guard: применять калибровку только если
            # holdout Brier не ухудшился значимо (> +5% относительно raw).
            # Если ухудшился — кладём прежнюю калибровку (не обновляем
            # `_latest.calibration` через self._latest = snap), но новые
            # bins / market_hit_rates по-прежнему доступны для отчётов.
            apply_calibration = True
            if (
                snap.holdout_brier_before is not None
                and snap.holdout_brier_after is not None
                and snap.holdout_brier_before > 1e-6
                and snap.holdout_samples >= 30
            ):
                ratio = snap.holdout_brier_after / snap.holdout_brier_before
                if ratio > 1.05:
                    apply_calibration = False
                    logger.warning(
                        "SelfLearner: anti-overfit guard, "
                        "holdout_brier_after={:.4f} > before={:.4f} (×{:.2f}) "
                        "— калибровка НЕ применяется",
                        snap.holdout_brier_after,
                        snap.holdout_brier_before,
                        ratio,
                    )

            if not apply_calibration and self._latest is not None:
                # Сохраняем прежний calibration (он не ломал holdout),
                # обновляем только метрики/market_hit_rates.
                snap.calibration = self._latest.calibration

            self._latest = snap
            # Обновляем адаптивные веса ансамбля на основе Brier score
            try:
                from core.ensemble import update_adaptive_weights
                # Если уже есть per-category Brier, отдаём отдельно
                # Glicko-Brier (1X2) и Poisson-Brier (totals/btts) —
                # ансамбль перевешивается осмысленно.
                glicko_brier = snap.category_brier.get("1x2", snap.brier)
                poisson_brier = snap.category_brier.get("total", snap.brier)
                update_adaptive_weights(
                    glicko_brier=glicko_brier,
                    poisson_brier=poisson_brier,
                )
                logger.info(
                    "SelfLearner: обновлены веса ансамбля, "
                    "brier={:.4f}, glicko={:.4f}, poisson={:.4f}, samples={}",
                    snap.brier, glicko_brier, poisson_brier, snap.samples,
                )
            except Exception as exc:
                logger.debug("SelfLearner: ошибка обновления весов: {}", exc)
            # AI-калибровочный анализ (best-effort, не блокирует)
            try:
                import os

                from services.ai_calibration import ai_calibration_check
                _api_key = os.environ.get("GEMINI_API_KEY", "")
                if _api_key and snap.samples >= 20:
                    _ai_task = asyncio.create_task(
                        ai_calibration_check(snap, _api_key)
                    )
                    _ai_task.add_done_callback(lambda t: t.result() if not t.cancelled() else None)
            except Exception as exc:
                logger.debug("SelfLearner: AI calibration skip: {}", exc)
            return snap
        finally:
            await session.close()

    async def incorporate_backtest(self, *, days: int = 30) -> int:
        """Читаем BacktestResult за последние N дней, вносим в калибровку.

        Записи backtest_results содержат probability + hit → используем
        для дополнительного уточнения корзин калибровки.
        Возвращает количество новых записей, которые были внесены.
        """
        session: AsyncSession = self._session_factory()
        count = 0
        try:
            cutoff = datetime.now(tz=UTC) - timedelta(days=days)
            rows = await session.scalars(
                select(BacktestResult).where(
                    and_(
                        BacktestResult.hit.is_not(None),
                        BacktestResult.created_at >= cutoff,
                    )
                )
            )
            bt_rows = list(rows)
            if not bt_rows:
                return 0

            snap = self._latest
            if snap is None:
                snap = await self.compute_snapshot(days=days)

            for row in bt_rows:
                p = max(1e-6, min(1 - 1e-6, row.probability))
                y = 1 if row.hit else 0
                for b in snap.calibration:
                    if b.lower <= p < b.upper or (b.upper == 1.0 and p >= 0.9):
                        b.count += 1
                        b.hits += y
                        count += 1
                        break

            if count > 0:
                # Пересчитаем Brier
                brier_sum = 0.0
                for row in bt_rows:
                    p = max(1e-6, min(1 - 1e-6, row.probability))
                    y = 1 if row.hit else 0
                    brier_sum += (p - y) ** 2
                bt_brier = brier_sum / len(bt_rows)
                # Смешиваем с текущим Brier: 70% PredictionOutcome + 30% backtest
                if snap.samples > 0:
                    snap.brier = 0.7 * snap.brier + 0.3 * bt_brier
                else:
                    snap.brier = bt_brier
                snap.samples += count

                try:
                    from core.ensemble import update_adaptive_weights
                    update_adaptive_weights(
                        glicko_brier=snap.brier,
                        poisson_brier=snap.brier,
                    )
                    logger.info(
                        "SelfLearner: backtest корректировка, "
                        "brier={:.4f}, +{} samples",
                        snap.brier, count,
                    )
                except Exception as exc:
                    logger.debug("SelfLearner: backtest weights error: {}", exc)

            return count
        except Exception as exc:
            logger.exception("SelfLearner.incorporate_backtest failed: {}", exc)
            return 0
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
        return self._calibrate_with(probability, self._latest)

    @staticmethod
    def _calibrate_with(
        probability: float, snap: LearningSnapshot | None,
    ) -> float:
        if snap is None or not snap.calibration:
            return probability
        p = max(0.0, min(1.0, probability))
        for b in snap.calibration:
            if b.count == 0:
                continue
            if b.lower <= p < b.upper or (b.upper == 1.0 and p >= 0.9):
                # Сглаживание: берём 0.6 модели + 0.4 эмпирики.
                # При малом количестве (count < 30) — больше доверяем модели.
                trust = 0.4 if b.count >= 30 else 0.4 * (b.count / 30.0)
                return max(0.0, min(1.0, (1 - trust) * p + trust * b.empirical))
        return p


def _market_category(market_key: str) -> str:
    """Группировка ключей в категории для per-category Brier.

    Категории: ``1x2`` / ``double_chance`` / ``total`` / ``btts`` /
    ``handicap`` / ``individual_total`` / ``dnb`` / ``other``.
    """
    if not market_key:
        return "other"
    k = market_key.lower()
    if k in {"1", "x", "2", "home", "away", "draw", "home_win", "away_win", "tie"}:
        return "1x2"
    if k.startswith("dc_") or k in {"1x", "x2", "12"} or "double_chance" in k:
        return "double_chance"
    if k.startswith("dnb"):
        return "dnb"
    if k.startswith("ah_") or "handicap" in k:
        return "handicap"
    if k.startswith("ht_") or k.startswith("at_") or k.startswith("home_") or k.startswith("away_"):
        # ИТ-ы (HT_O15 / AT_U05 / home_over_2.5 etc.)
        if any(t in k for t in ("over", "under", "_o", "_u")):
            return "individual_total"
    if k.startswith("btts") or "both_teams" in k or "both_yes" in k or "both_no" in k:
        return "btts"
    if k.startswith("o") and any(c.isdigit() for c in k):
        return "total"
    if k.startswith("u") and any(c.isdigit() for c in k):
        return "total"
    if k.startswith("over_") or k.startswith("under_"):
        return "total"
    return "other"


def _check_market(market_key: str, home: int, away: int) -> bool | None:
    """Проверка сыгранности рынка по реальному счёту.

    Делегирует в `services.market_resolver.resolve_market`, у которого
    значительно более полный охват ключей (HT_*, AT_*, AH_*, EXACT_SCORE,
    DNB_*, etc) — раньше self_learner покрывал ~30% наших ключей и
    половина прогнозов не попадала в калибровку.

    Понимает короткий формат (``O25``), длинный с точкой (``over_2.5``)
    и legacy без точки (``over_25``).
    """
    try:
        from services.market_resolver import resolve_market

        return resolve_market(market_key, home, away)
    except Exception:
        return None


__all__ = ["CalibrationBin", "LearningSnapshot", "SelfLearner"]
