"""Аналитика прогнозов: tracking точности, ROI, логирование ставок.

Используется:
- для /admin_stats — топ-метрики платформы.
- для /my_analytics — статистика пользователя (если есть история запросов).
- для автоматической проверки точности прогнозов после окончания матчей.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from statistics import mean

from core.value_calculator import ValueBet
from services.prediction_service import PredictionResult


@dataclass(slots=True)
class PredictionTick:
    """Одна точка истории: сам прогноз + итоговый результат (если есть)."""

    game_id: int
    created_at: datetime
    predicted_market: str
    predicted_prob: float
    actual_odds: float
    fair_odds: float
    value_percent: float
    settled: bool = False  # был ли уже рассчитан
    won: bool | None = None  # True/False/None
    home_score: int | None = None
    away_score: int | None = None


@dataclass(slots=True)
class AnalyticsSummary:
    total_predictions: int = 0
    settled: int = 0
    won: int = 0
    lost: int = 0
    hit_rate_pct: float = 0.0
    roi_pct: float = 0.0  # прибыль в % от объёма ставок
    avg_value_pct: float = 0.0
    avg_odds: float = 0.0
    best_streak: int = 0
    worst_streak: int = 0
    markets_breakdown: dict[str, int] = field(default_factory=dict)


class AnalyticsService:
    """Простейший in-memory учёт ставок (в продакшене — БД)."""

    def __init__(self) -> None:
        self._history: list[PredictionTick] = []

    def record_prediction(
        self, result: PredictionResult, bet: ValueBet, now: datetime | None = None
    ) -> PredictionTick:
        tick = PredictionTick(
            game_id=result.game_id,
            created_at=now or datetime.utcnow(),
            predicted_market=bet.market_key,
            predicted_prob=bet.probability,
            actual_odds=bet.actual_odds,
            fair_odds=bet.fair_odds,
            value_percent=bet.value_percent,
        )
        self._history.append(tick)
        return tick

    def settle(
        self,
        game_id: int,
        *,
        home_score: int,
        away_score: int,
        market_resolver: callable = lambda key, h, a: False,
    ) -> int:
        """Проходим по истории и закрываем все ставки на этот матч."""
        closed = 0
        for tick in self._history:
            if tick.game_id != game_id or tick.settled:
                continue
            tick.home_score = home_score
            tick.away_score = away_score
            tick.won = bool(
                market_resolver(tick.predicted_market, home_score, away_score)
            )
            tick.settled = True
            closed += 1
        return closed

    def summary(self) -> AnalyticsSummary:
        total = len(self._history)
        if total == 0:
            return AnalyticsSummary()
        settled = [t for t in self._history if t.settled]
        won = sum(1 for t in settled if t.won is True)
        lost = sum(1 for t in settled if t.won is False)
        hit_rate = (won / len(settled) * 100.0) if settled else 0.0

        # ROI: условно ставим по 1 единице на каждую
        profit = 0.0
        for t in settled:
            if t.won is True:
                profit += t.actual_odds - 1.0
            elif t.won is False:
                profit -= 1.0
        roi = (profit / len(settled) * 100.0) if settled else 0.0

        # Стрики
        best_streak = worst_streak = cur_best = cur_worst = 0
        for t in settled:
            if t.won is True:
                cur_best += 1
                cur_worst = 0
                best_streak = max(best_streak, cur_best)
            elif t.won is False:
                cur_worst += 1
                cur_best = 0
                worst_streak = max(worst_streak, cur_worst)

        markets = Counter(t.predicted_market for t in self._history)

        return AnalyticsSummary(
            total_predictions=total,
            settled=len(settled),
            won=won,
            lost=lost,
            hit_rate_pct=hit_rate,
            roi_pct=roi,
            avg_value_pct=(mean(t.value_percent for t in self._history)) if total else 0.0,
            avg_odds=(mean(t.actual_odds for t in self._history)) if total else 0.0,
            best_streak=best_streak,
            worst_streak=worst_streak,
            markets_breakdown=dict(markets),
        )

    def by_user_range(self, days: int) -> list[PredictionTick]:
        """Отдаёт все тики за последние N дней (можно фильтровать на вызове)."""
        cutoff = datetime.utcnow()
        return [
            t for t in self._history
            if (cutoff - t.created_at).days <= days
        ]

    @property
    def history(self) -> list[PredictionTick]:
        return list(self._history)

    def clear(self) -> None:
        self._history.clear()

    def __len__(self) -> int:
        return len(self._history)


__all__ = ["AnalyticsService", "AnalyticsSummary", "PredictionTick"]
