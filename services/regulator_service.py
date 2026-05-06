"""Сервис применения ProbabilityRegulator к результату прогноза.

Обращается к таблицам `match_results` (исторические матчи) и
`prediction_outcomes` (наша обратная связь). Не делает HTTP-запросов.
"""
from __future__ import annotations

from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from core.probability_regulator import (
    HistoricalRow,
    RegulationResult,
    aggregate_feedback,
    regulate,
)
from db.models import MatchResult, PredictionOutcome


class RegulatorService:
    def __init__(
        self,
        session: AsyncSession,
        *,
        history_window: int = 200,
    ) -> None:
        self._session = session
        self._history_window = history_window

    async def _load_history(self, league_id: int | None) -> list[HistoricalRow]:
        if not league_id:
            return []
        rows = (
            await self._session.scalars(
                select(MatchResult)
                .where(
                    MatchResult.league_id == league_id,
                    MatchResult.home_score.is_not(None),
                    MatchResult.away_score.is_not(None),
                )
                .order_by(desc(MatchResult.date))
                .limit(self._history_window)
            )
        ).all()
        return [
            HistoricalRow(home_score=r.home_score, away_score=r.away_score)
            for r in rows
            if r.home_score is not None and r.away_score is not None
        ]

    async def _load_feedback(self) -> dict[str, tuple[int, int]]:
        rows = (
            await self._session.scalars(
                select(PredictionOutcome).where(
                    PredictionOutcome.hit.is_not(None),
                )
            )
        ).all()
        return aggregate_feedback(
            (r.market_key, r.hit) for r in rows
        )

    async def regulate(
        self,
        probabilities: dict[str, float],
        *,
        league_id: int | None,
    ) -> dict[str, RegulationResult]:
        history = await self._load_history(league_id)
        feedback = await self._load_feedback()
        return regulate(
            probabilities, history, feedback_hitrates=feedback,
        )


__all__ = ["RegulatorService"]
