"""Запись и резолв полной истории всех пиков по матчу.

В отличие от `PredictionOutcome`, который сохраняет только главный
пик + value-беты, эта таблица хранит ВСЕ ~40 рынков, посчитанных
моделью на матч. Нужна для:

  * `SecondaryPickCalibrator` — empirical hit-rate per market_key
    при разных условиях (например, «когда главный пик пролетел»).
  * Будущих исследований — сравнить, какие рынки реально
    калиброваны лучше у разных лиг.

Заполняется из:
  * `bot/handlers/predictions.py` — live-прогноз (is_backtest=False)
  * `services/backtester.py` — бэктест (is_backtest=True)

Резолвится через `resolve_pending_picks()` — отдельный фоновый таск,
дополняющий `SelfLearner.evaluate_pending`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from loguru import logger
from sqlalchemy import and_, select
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import MatchPickHistory, MatchResult


@dataclass(slots=True, frozen=True)
class PickSnapshot:
    """Один пик в момент прогнозирования матча."""

    market_key: str
    probability: float
    fair_odds: float | None = None


def _market_category(market_key: str) -> str:
    """Дублирование _market_category из self_learner для независимости.

    Не импортируем напрямую чтобы не создавать циклов.
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
    if k.startswith(("ht_", "at_", "home_", "away_")):
        if any(t in k for t in ("over", "under", "_o", "_u")):
            return "individual_total"
    if k.startswith("btts") or "both_teams" in k or "both_yes" in k or "both_no" in k:
        return "btts"
    if k.startswith("o") and any(c.isdigit() for c in k):
        return "total"
    if k.startswith("u") and any(c.isdigit() for c in k):
        return "total"
    if k.startswith(("over_", "under_")):
        return "total"
    return "other"


async def record_picks(
    session: AsyncSession,
    *,
    game_id: int,
    league_id: int | None,
    picks: list[PickSnapshot],
    main_pick_key: str | None,
    is_backtest: bool = False,
    home_score: int | None = None,
    away_score: int | None = None,
) -> int:
    """Сохранить набор пиков в `match_pick_history`.

    UPSERT по (game_id, market_key, is_backtest) — повторный вызов
    обновляет вероятность, не создаёт дубликаты. Возвращает кол-во
    затронутых строк.
    """
    if not picks:
        return 0
    n = 0
    for pick in picks:
        if not pick.market_key:
            continue
        is_main = pick.market_key == main_pick_key
        try:
            stmt = sqlite_insert(MatchPickHistory).values(
                game_id=int(game_id),
                league_id=league_id,
                market_key=pick.market_key,
                market_category=_market_category(pick.market_key),
                predicted_probability=float(
                    max(0.0, min(1.0, pick.probability)),
                ),
                fair_odds=(
                    float(pick.fair_odds)
                    if pick.fair_odds and pick.fair_odds > 1.001
                    else None
                ),
                is_main_pick=bool(is_main),
                is_backtest=bool(is_backtest),
                home_score=home_score,
                away_score=away_score,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["game_id", "market_key", "is_backtest"],
                set_={
                    "predicted_probability": stmt.excluded.predicted_probability,
                    "fair_odds": stmt.excluded.fair_odds,
                    "is_main_pick": stmt.excluded.is_main_pick,
                    "league_id": stmt.excluded.league_id,
                    "market_category": stmt.excluded.market_category,
                },
            )
            await session.execute(stmt)
            n += 1
        except Exception as exc:
            logger.debug(
                "match_pick_history upsert failed game={} market={}: {}",
                game_id, pick.market_key, exc,
            )
    return n


async def resolve_pending_picks(
    session_factory: Any,
    *,
    limit: int = 5000,
) -> int:
    """Заполнить hit / main_pick_hit для пиков, у которых счёт уже известен.

    1. Берём пики с `hit IS NULL`.
    2. Соединяем с `MatchResult` по game_id.
    3. Через `resolve_market` ставим hit для каждого.
    4. После того как все пики матча обработаны, проставляем
       `main_pick_hit` всем пикам этого матча на основании главного.
    """
    from services.market_resolver import resolve_market

    session: AsyncSession = session_factory()
    updated = 0
    try:
        rows = await session.scalars(
            select(MatchPickHistory)
            .where(MatchPickHistory.hit.is_(None))
            .limit(limit),
        )
        picks = list(rows)
        if not picks:
            return 0
        game_ids = {p.game_id for p in picks}
        results_rows = await session.scalars(
            select(MatchResult).where(MatchResult.game_id.in_(list(game_ids))),
        )
        results = {r.game_id: r for r in results_rows}
        # Группируем по game_id для последующей простановки main_pick_hit
        by_game: dict[int, list[MatchPickHistory]] = {}
        for p in picks:
            r = results.get(p.game_id)
            if r is None or r.home_score is None or r.away_score is None:
                continue
            try:
                hit = resolve_market(
                    p.market_key, int(r.home_score), int(r.away_score),
                )
            except Exception:
                hit = None
            if hit is None:
                continue
            p.hit = bool(hit)
            p.home_score = int(r.home_score)
            p.away_score = int(r.away_score)
            p.evaluated_at = datetime.now(tz=UTC)
            by_game.setdefault(p.game_id, []).append(p)
            updated += 1

        # Дополнительный проход: проставить main_pick_hit всем пикам матча
        # (включая ранее обработанные).
        for game_id, _picks in by_game.items():
            main_hit_row = await session.scalar(
                select(MatchPickHistory.hit).where(
                    and_(
                        MatchPickHistory.game_id == game_id,
                        MatchPickHistory.is_main_pick.is_(True),
                        MatchPickHistory.is_backtest.is_(False),
                        MatchPickHistory.hit.is_not(None),
                    ),
                ),
            )
            if main_hit_row is None:
                continue
            all_picks = await session.scalars(
                select(MatchPickHistory).where(
                    MatchPickHistory.game_id == game_id,
                ),
            )
            for ap in all_picks:
                ap.main_pick_hit = bool(main_hit_row)

        await session.commit()
    except Exception as exc:
        logger.exception("resolve_pending_picks failed: {}", exc)
        await session.rollback()
    finally:
        await session.close()
    return updated


__all__ = [
    "PickSnapshot",
    "record_picks",
    "resolve_pending_picks",
]
