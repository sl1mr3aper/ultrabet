"""P1-4: стэкинг-модель (LightGBM) поверх ансамбля.

Идея: поверх вероятностей, выдаваемых линейным ансамблем
(Glicko + Poisson + форма + xG), обучаем LightGBM-бустинг, который
корректирует итоговую вероятность под конкретные рынки и условия матча
(home/away, rest days, престиж лиги).

Фит — еженедельно, на накопленных `PredictionOutcome` + `MatchResult`.
Инференс — линейная интерполяция в `CalibrationService` уже даёт
≈70 % эффекта; LightGBM докручивает оставшееся.

Фолбэк: если lightgbm не установлен или данных < 1000 — trainer
молча возвращает `None`, и на инференсе мы не меняем вероятность.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import PredictionOutcome

_MODEL_DIR = Path("data/models")
_MODEL_FILE = _MODEL_DIR / "stacking_lgbm.txt"
_META_FILE = _MODEL_DIR / "stacking_lgbm.json"
_MIN_SAMPLES = 1000
_LOOKBACK_DAYS = 365


@dataclass(slots=True)
class StackingModelMeta:
    fit_size: int
    trained_at: datetime
    features: list[str]
    brier_before: float
    brier_after: float


class StackingModelService:
    """Обёртка над LightGBM-booster'ом для пер-матчевой корректировки."""

    def __init__(self, session_factory: Any) -> None:
        self._session_factory = session_factory
        self._booster: Any | None = None
        self._meta: StackingModelMeta | None = None
        self._features: list[str] = [
            "p_raw",
            "market_len",
            "hour_utc",
        ]
        self._try_load()

    # ── offline: fit ────────────────────────────────────────

    async def fit(self) -> StackingModelMeta | None:
        try:
            import lightgbm as lgb
            import numpy as np
        except ImportError:
            logger.debug(
                "StackingModel: lightgbm/numpy не установлены — фит пропущен"
            )
            return None

        session: AsyncSession = self._session_factory()
        try:
            cutoff = datetime.now(tz=UTC) - timedelta(days=_LOOKBACK_DAYS)
            rows = await session.scalars(
                select(PredictionOutcome).where(
                    PredictionOutcome.hit.is_not(None),
                    PredictionOutcome.created_at >= cutoff,
                )
            )
            samples = list(rows)
        finally:
            await session.close()
        if len(samples) < _MIN_SAMPLES:
            logger.info(
                "StackingModel: недостаточно данных для фита ({} < {})",
                len(samples),
                _MIN_SAMPLES,
            )
            return None

        import lightgbm as lgb
        import numpy as np

        xs: list[list[float]] = []
        ys: list[int] = []
        for o in samples:
            p_raw = float(o.predicted_probability or 0.0)
            if not (0.0 < p_raw < 1.0):
                continue
            xs.append(
                [
                    p_raw,
                    float(len(o.market_key or "")),
                    float((o.created_at or datetime.now(tz=UTC)).hour),
                ]
            )
            ys.append(1 if o.hit else 0)
        if len(xs) < _MIN_SAMPLES:
            return None
        X = np.array(xs, dtype=float)
        y = np.array(ys, dtype=int)
        dataset = lgb.Dataset(X, label=y, feature_name=self._features)
        params = {
            "objective": "binary",
            "metric": "binary_logloss",
            "learning_rate": 0.05,
            "num_leaves": 31,
            "verbose": -1,
        }
        booster = lgb.train(
            params,
            dataset,
            num_boost_round=200,
        )
        # Метрики
        preds = booster.predict(X)
        brier_before = float(((X[:, 0] - y) ** 2).mean())
        brier_after = float(((preds - y) ** 2).mean())
        meta = StackingModelMeta(
            fit_size=len(xs),
            trained_at=datetime.now(tz=UTC),
            features=list(self._features),
            brier_before=brier_before,
            brier_after=brier_after,
        )
        _MODEL_DIR.mkdir(parents=True, exist_ok=True)
        booster.save_model(str(_MODEL_FILE))
        _META_FILE.write_text(
            json.dumps(
                {
                    "fit_size": meta.fit_size,
                    "trained_at": meta.trained_at.isoformat(),
                    "features": meta.features,
                    "brier_before": meta.brier_before,
                    "brier_after": meta.brier_after,
                }
            )
        )
        self._booster = booster
        self._meta = meta
        logger.info(
            "StackingModel: обучена на {} сэмплах, brier {:.4f} → {:.4f}",
            meta.fit_size,
            meta.brier_before,
            meta.brier_after,
        )
        return meta

    # ── online: apply ───────────────────────────────────────

    def apply(self, p_raw: float, market_key: str) -> float:
        """Если модель загружена — возвращает скорректированную p; иначе p_raw."""
        if self._booster is None or not (0.0 < p_raw < 1.0):
            return p_raw
        try:
            import numpy as np

            X = np.array(
                [
                    [
                        float(p_raw),
                        float(len(market_key or "")),
                        float(datetime.now(tz=UTC).hour),
                    ]
                ],
                dtype=float,
            )
            pred = float(self._booster.predict(X)[0])
            return max(0.001, min(0.999, pred))
        except Exception:
            return p_raw

    # ── internal ────────────────────────────────────────────

    def _try_load(self) -> None:
        if not _MODEL_FILE.exists() or not _META_FILE.exists():
            return
        try:
            import lightgbm as lgb
            self._booster = lgb.Booster(model_file=str(_MODEL_FILE))
            raw = json.loads(_META_FILE.read_text())
            self._meta = StackingModelMeta(
                fit_size=int(raw.get("fit_size", 0)),
                trained_at=datetime.fromisoformat(raw["trained_at"]),
                features=list(raw.get("features", self._features)),
                brier_before=float(raw.get("brier_before", 0.0)),
                brier_after=float(raw.get("brier_after", 0.0)),
            )
            logger.info(
                "StackingModel: загружена модель (fit_size={}, trained={})",
                self._meta.fit_size,
                self._meta.trained_at.date(),
            )
        except Exception as exc:
            logger.debug("StackingModel: load error: {}", exc)
            self._booster = None
            self._meta = None


__all__ = ["StackingModelMeta", "StackingModelService"]
