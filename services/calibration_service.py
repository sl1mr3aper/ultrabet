"""P0-2: активный калибровочный цикл (Platt + Isotonic) для прогнозов.

Раз в сутки:
1. Берём все `PredictionOutcome` за 90 дней с `hit ∈ {True, False}`.
2. По каждому `market_key` с ≥ 100 наблюдений фитим `IsotonicRegression`
   на паре `(p_raw → hit 0/1)`.
3. Сохраняем монотонную кривую как JSON в `CalibrationSnapshot`.
4. В рантайме `CalibrationService.calibrate(market, p_raw)` берёт
   последний снимок и интерполирует `p`.

Фолбэк: если модель sklearn недоступна или данных мало — возвращаем
`p_raw` без изменений (graceful degrade).
"""

from __future__ import annotations

import json
from bisect import bisect_left
from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import CalibrationSnapshot, PredictionOutcome

_MIN_SAMPLES_PER_MARKET = 30
_LOOKBACK_DAYS = 90
_HOLDOUT_DAYS = 14
_CACHE_TTL_SECONDS = 6 * 3600


class CalibrationService:
    """Фит + онлайн-применение изотонической калибровки по рынкам."""

    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory
        # In-memory кэш: market_key → (xs, ys, fetched_at)
        self._cache: dict[str, tuple[list[float], list[float], datetime]] = {}

    # ── offline: фит раз в сутки ──────────────────────────────────

    async def fit_all(self) -> dict[str, int]:
        """Переобучает калибровку по всем рынкам с holdout-валидацией.

        Train/holdout split: данные старше HOLDOUT_DAYS дней — train,
        последние HOLDOUT_DAYS — holdout. Если holdout Brier хуже
        исходного — не сохраняем калибровку (anti-overfit guard).

        Возвращает {market_key: fit_size} для логов.
        """
        try:
            from sklearn.isotonic import IsotonicRegression  # noqa: F401
        except ImportError:
            logger.warning(
                "CalibrationService: sklearn не установлен — калибровка пропущена"
            )
            return {}

        session: AsyncSession = self._session_factory()
        stats: dict[str, int] = {}
        try:
            cutoff = datetime.now(tz=UTC) - timedelta(days=_LOOKBACK_DAYS)
            holdout_cutoff = datetime.now(tz=UTC) - timedelta(days=_HOLDOUT_DAYS)
            rows = await session.scalars(
                select(PredictionOutcome).where(
                    PredictionOutcome.hit.is_not(None),
                    PredictionOutcome.created_at >= cutoff,
                )
            )
            by_market_train: dict[str, list[tuple[float, int]]] = {}
            by_market_holdout: dict[str, list[tuple[float, int]]] = {}
            for o in rows:
                if o.market_key and o.predicted_probability is not None:
                    entry = (float(o.predicted_probability), 1 if o.hit else 0)
                    created = getattr(o, "created_at", None)
                    if created and created >= holdout_cutoff:
                        by_market_holdout.setdefault(o.market_key, []).append(entry)
                    else:
                        by_market_train.setdefault(o.market_key, []).append(entry)
            for market, train_data in by_market_train.items():
                if len(train_data) < _MIN_SAMPLES_PER_MARKET:
                    continue
                curve_xs, curve_ys, brier_before, brier_after = (
                    self._fit_isotonic(train_data)
                )
                if not curve_xs:
                    continue
                # Holdout validation: проверяем, что калибровка не ухудшает
                holdout = by_market_holdout.get(market, [])
                if holdout and len(holdout) >= 5:
                    holdout_brier_before = sum(
                        (p - h) ** 2 for p, h in holdout
                    ) / len(holdout)
                    holdout_brier_after = sum(
                        (_interp(curve_xs, curve_ys, p) - h) ** 2
                        for p, h in holdout
                    ) / len(holdout)
                    if holdout_brier_after > holdout_brier_before * 1.05:
                        logger.info(
                            "CalibrationService: {}: holdout worse "
                            "({:.4f} > {:.4f}), skip",
                            market, holdout_brier_after, holdout_brier_before,
                        )
                        continue
                snapshot = CalibrationSnapshot(
                    market_key=market,
                    curve_json=json.dumps(
                        [{"x": float(x), "y": float(y)}
                         for x, y in zip(curve_xs, curve_ys, strict=False)]
                    ),
                    fit_size=len(train_data),
                    brier_before=brier_before,
                    brier_after=brier_after,
                )
                session.add(snapshot)
                stats[market] = len(train_data)
                self._cache.pop(market, None)
            await session.commit()
        finally:
            await session.close()
        if stats:
            logger.info(
                "CalibrationService: переобучено {} рынков ({})",
                len(stats),
                ", ".join(f"{k}={v}" for k, v in list(stats.items())[:5]),
            )
        return stats

    @staticmethod
    def _fit_isotonic(
        data: list[tuple[float, int]],
    ) -> tuple[list[float], list[float], float, float]:
        """Фитим IsotonicRegression, возвращаем (xs, ys, brier_before, brier_after)."""
        from sklearn.isotonic import IsotonicRegression

        xs = [p for p, _ in data]
        ys = [h for _, h in data]
        # Brier до калибровки
        brier_before = sum((p - h) ** 2 for p, h in data) / len(data)
        model = IsotonicRegression(out_of_bounds="clip", y_min=0.001, y_max=0.999)
        model.fit(xs, ys)
        # Сжимаем кривую до 24 опорных точек для быстрой интерполяции в рантайме.
        anchors = [i / 24.0 for i in range(25)]
        mapped = model.predict(anchors)
        curve_xs = [float(a) for a in anchors]
        curve_ys = [float(v) for v in mapped]
        # Brier после
        predicted_after = model.predict(xs)
        brier_after = sum(
            (pa - h) ** 2 for pa, h in zip(predicted_after, ys, strict=False)
        ) / len(data)
        return curve_xs, curve_ys, float(brier_before), float(brier_after)

    # ── online: применение при инференсе ──────────────────────────

    async def calibrate(self, market_key: str, p_raw: float) -> float:
        """Возвращает калиброванную вероятность. Если снимка нет — p_raw."""
        if p_raw <= 0 or p_raw >= 1:
            return p_raw
        curve = await self._get_curve(market_key)
        if not curve:
            return p_raw
        xs, ys = curve
        return _interp(xs, ys, p_raw)

    async def _get_curve(
        self, market_key: str
    ) -> tuple[list[float], list[float]] | None:
        now = datetime.now(tz=UTC)
        cached = self._cache.get(market_key)
        if cached is not None:
            xs, ys, fetched = cached
            if (now - fetched).total_seconds() < _CACHE_TTL_SECONDS:
                return (xs, ys) if xs else None
        # Тянем последний снимок
        session: AsyncSession = self._session_factory()
        try:
            snap = await session.scalar(
                select(CalibrationSnapshot)
                .where(CalibrationSnapshot.market_key == market_key)
                .order_by(CalibrationSnapshot.created_at.desc())
                .limit(1)
            )
        finally:
            await session.close()
        if snap is None:
            self._cache[market_key] = ([], [], now)
            return None
        try:
            points = json.loads(snap.curve_json)
            xs = [float(pt["x"]) for pt in points]
            ys = [float(pt["y"]) for pt in points]
        except (ValueError, KeyError, TypeError):
            self._cache[market_key] = ([], [], now)
            return None
        self._cache[market_key] = (xs, ys, now)
        return (xs, ys)


def _interp(xs: list[float], ys: list[float], x: float) -> float:
    """Линейная интерполяция по опорным точкам изотонической кривой."""
    if not xs:
        return x
    if x <= xs[0]:
        return ys[0]
    if x >= xs[-1]:
        return ys[-1]
    idx = bisect_left(xs, x)
    x0, x1 = xs[idx - 1], xs[idx]
    y0, y1 = ys[idx - 1], ys[idx]
    if x1 == x0:
        return y0
    return y0 + (y1 - y0) * (x - x0) / (x1 - x0)


__all__ = ["CalibrationService"]
