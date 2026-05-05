"""Глобальный реестр сервисов, доступный из handlers.

В aiogram 3.27+ Bot не поддерживает item assignment, поэтому храним
сервисы здесь, а main.py заполняет их при старте.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from api.sstats_client import SStatsClient
    from config import Settings
    from services.ai_refiner import GeminiRefiner
    from services.analytics import AnalyticsService
    from services.cache_warmer import CacheWarmer
    from services.calibration_service import CalibrationService
    from services.history_backfill import HistoryBackfillService
    from services.kv_cache import KVCache
    from services.league_aggregate_service import LeagueAggregateService
    from services.pick_adjustment_cache import PickAdjustmentCache
    from services.predictions_resolver import PredictionsResolver
    from services.self_learner import SelfLearner
    from services.topmatches_precompute import TopMatchesPrecompute


class _Services:
    settings: Settings | None = None
    sstats: SStatsClient | None = None
    session_factory: object | None = None
    analytics: AnalyticsService | None = None
    self_learner: SelfLearner | None = None
    ai_refiner: GeminiRefiner | None = None
    history_backfill: HistoryBackfillService | None = None
    predictions_resolver: PredictionsResolver | None = None
    calibration: CalibrationService | None = None
    cache_warmer: CacheWarmer | None = None
    topmatches_precompute: TopMatchesPrecompute | None = None
    kv_cache: KVCache | None = None
    league_aggregates: LeagueAggregateService | None = None
    # SecondaryPickCalibrator кэш: дёргается в PredictionService.predict()
    # чтобы применить эмпирические adjustment_factor'ы. Заполняется
    # фоновым refresh-loop'ом раз в час.
    pick_adjustments: PickAdjustmentCache | None = None


services = _Services()


__all__ = ["services"]
