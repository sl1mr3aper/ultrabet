"""Авто-резолвер прогнозов: проставляет hit/miss и сохраняет счёт.

Отличие от `SelfLearner.evaluate_pending()`:
- Тот ищет фактический счёт ТОЛЬКО в локальной таблице `MatchResult`,
  а её заполняет `HistoryBackfillService` лишь по топ-30 лигам.
- Этот резолвер дополнительно «доливает» счёт через
  `sstats_client.get_game(game_id)` — для лиг, которых нет в backfill.
- Найденный счёт мы сохраняем в `MatchResult` (upsert) — следующие
  обращения за тем же game_id будут отвечать из кэша БД.
- Затем резолвим все `PredictionOutcome` записи по этому game_id
  через `services.market_resolver.resolve_market`.

Это даёт пользователю автоматически обновляемую историю прогнозов:
для уже сыгранных матчей появятся ✅/❌ и реальный счёт.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from api.sstats_client import SStatsClient
from db.models import MatchResult, PredictionOutcome
from services.history_backfill import _extract_score
from services.market_resolver import resolve_market


def _unwrap_game(payload: Any) -> dict[str, Any] | None:
    """SStats `/Games/{id}` возвращает `{"game": {...}, "statistics": ...,
    "lineups": ..., ...}`. А `/Games/list` — плоский dict игры.
    Здесь приводим оба формата к единому виду — флэт-словарь игры —
    чтобы `_extract_score` / `_upsert_result` работали единообразно.
    """
    if not isinstance(payload, dict):
        return None
    inner = payload.get("game")
    if isinstance(inner, dict):
        return inner
    return payload


class PredictionsResolver:
    """Резолвит pending PredictionOutcome → hit/miss + сохраняет счёт."""

    def __init__(self, client: SStatsClient, session_factory: Any) -> None:
        self._client = client
        self._session_factory = session_factory

    async def resolve_pending(self, *, max_games: int = 200) -> int:
        """Один проход. Возвращает количество резолвенных outcomes.

        Алгоритм:
        1. Берём pending outcomes (`hit IS NULL`), группируем по game_id,
           самые свежие сверху (limit на game_id, не на outcomes).
        2. По каждому game_id:
           a. Если в `MatchResult` уже есть счёт — используем его.
           b. Иначе тянем `get_game(game_id)` из SStats. Если матч завершён
              и счёт распарсился — пишем upsert в `MatchResult`.
        3. Резолвим все pending outcomes этого game_id: проставляем
           hit (True/False) через `resolve_market`. None — рынок неизвестный
           или счёт не получен.
        """
        session: AsyncSession = self._session_factory()
        resolved = 0
        try:
            # все pending записи (не более ~5000 за проход — достаточно)
            rows = await session.scalars(
                select(PredictionOutcome)
                .where(PredictionOutcome.hit.is_(None))
                .order_by(PredictionOutcome.created_at.desc())
                .limit(5000)
            )
            outcomes = list(rows)
            if not outcomes:
                return 0

            # group by game_id, ограничиваем число уникальных game_id за проход
            by_game: dict[int, list[PredictionOutcome]] = {}
            for o in outcomes:
                by_game.setdefault(o.game_id, []).append(o)

            game_ids = list(by_game.keys())[:max_games]

            # 1) счёт из MatchResult
            existing = {
                r.game_id: r
                for r in (
                    await session.scalars(
                        select(MatchResult).where(
                            MatchResult.game_id.in_(game_ids),
                        )
                    )
                )
            }

            # 2) для game_id без MatchResult — пробуем SStats /Games/{id}
            for gid in game_ids:
                if gid in existing and existing[gid].home_score is not None:
                    continue
                try:
                    raw = await self._client.get_game(gid)
                except Exception as exc:
                    logger.debug("resolver: get_game({}) failed: {}", gid, exc)
                    continue
                game_obj = _unwrap_game(raw)
                if game_obj is None:
                    continue
                home_score = _extract_score(game_obj, "home")
                away_score = _extract_score(game_obj, "away")
                if home_score is None or away_score is None:
                    # ещё не сыгран / API не отдал — пропускаем
                    continue
                # upsert в MatchResult
                await self._upsert_result(
                    session, existing.get(gid), gid, game_obj,
                    home_score, away_score,
                )

            # пересчитываем доступные результаты
            score_map: dict[int, tuple[int, int]] = {}
            res_q = await session.scalars(
                select(MatchResult).where(MatchResult.game_id.in_(game_ids))
            )
            for r in res_q:
                if r.home_score is not None and r.away_score is not None:
                    score_map[r.game_id] = (r.home_score, r.away_score)

            # 3) резолвим outcomes
            for gid, outs in by_game.items():
                if gid not in score_map:
                    continue
                hs, as_ = score_map[gid]
                for o in outs:
                    try:
                        hit = resolve_market(o.market_key, hs, as_)
                    except Exception:
                        hit = None
                    if hit is None:
                        continue
                    o.hit = bool(hit)
                    o.evaluated_at = datetime.now(tz=UTC)
                    resolved += 1

            await session.commit()
        except Exception as exc:
            logger.exception("PredictionsResolver.resolve_pending failed: {}", exc)
            await session.rollback()
        finally:
            await session.close()
        if resolved:
            logger.info(
                "PredictionsResolver: резолвлено {} прогнозов", resolved,
            )
        return resolved

    async def ensure_match_result(self, game_id: int) -> bool:
        """Гарантирует наличие MatchResult со счётом для уже сыгранного матча.

        В отличие от `resolve_game`, не требует pending PredictionOutcome —
        просто тянет /Games/{id} от источника и сохраняет счёт. Нужен
        перед расчётом прогноза на прошлый матч, чтобы карточка прогноза
        показала «✅ Матч сыгран — итог: X:Y».
        Возвращает True, если в БД теперь есть итоговый счёт.
        """
        session: AsyncSession = self._session_factory()
        try:
            existing = await session.scalar(
                select(MatchResult).where(MatchResult.game_id == int(game_id))
            )
            if existing is not None and existing.home_score is not None:
                return True
            try:
                raw = await self._client.get_game(int(game_id))
            except Exception as exc:
                logger.debug(
                    "ensure_match_result: get_game({}) failed: {}",
                    game_id, exc,
                )
                return False
            game_obj = _unwrap_game(raw)
            if game_obj is None:
                return False
            home_score = _extract_score(game_obj, "home")
            away_score = _extract_score(game_obj, "away")
            if home_score is None or away_score is None:
                return False
            await self._upsert_result(
                session, existing, int(game_id), game_obj,
                home_score, away_score,
            )
            await session.commit()
            return True
        except Exception as exc:
            logger.debug(
                "ensure_match_result({}) failed: {}", game_id, exc,
            )
            await session.rollback()
            return False
        finally:
            await session.close()

    async def resolve_game(self, game_id: int) -> int:
        """Резолвит все pending outcomes для одного конкретного game_id.

        Используется сразу после расчёта прогноза на уже сыгранный матч:
        в этом случае мы не ждём следующего прохода фонового резолвера,
        а обновляем историю пользователя немедленно.
        """
        session: AsyncSession = self._session_factory()
        resolved = 0
        try:
            outcomes = list(
                await session.scalars(
                    select(PredictionOutcome).where(
                        PredictionOutcome.game_id == int(game_id),
                        PredictionOutcome.hit.is_(None),
                    )
                )
            )
            if not outcomes:
                return 0

            existing = await session.scalar(
                select(MatchResult).where(MatchResult.game_id == int(game_id))
            )
            if existing is None or existing.home_score is None:
                try:
                    raw = await self._client.get_game(int(game_id))
                except Exception as exc:
                    logger.debug(
                        "resolver: get_game({}) failed: {}", game_id, exc,
                    )
                    return 0
                game_obj = _unwrap_game(raw)
                if game_obj is None:
                    return 0
                home_score = _extract_score(game_obj, "home")
                away_score = _extract_score(game_obj, "away")
                if home_score is None or away_score is None:
                    return 0
                await self._upsert_result(
                    session, existing, int(game_id), game_obj,
                    home_score, away_score,
                )
                hs, as_ = home_score, away_score
            else:
                if existing.away_score is None:
                    return 0
                hs, as_ = existing.home_score, existing.away_score

            for o in outcomes:
                try:
                    hit = resolve_market(o.market_key, hs, as_)
                except Exception:
                    hit = None
                if hit is None:
                    continue
                o.hit = bool(hit)
                o.evaluated_at = datetime.now(tz=UTC)
                resolved += 1

            await session.commit()
        except Exception as exc:
            logger.debug(
                "PredictionsResolver.resolve_game({}) failed: {}",
                game_id, exc,
            )
            await session.rollback()
        finally:
            await session.close()
        return resolved

    async def _upsert_result(
        self,
        session: AsyncSession,
        existing: MatchResult | None,
        gid: int,
        game_obj: dict[str, Any],
        home_score: int,
        away_score: int,
    ) -> None:
        if existing is not None:
            existing.home_score = home_score
            existing.away_score = away_score
            return
        season = game_obj.get("season") or {}
        league = season.get("league") if isinstance(season, dict) else {}
        if not isinstance(league, dict):
            league = {}
        country = league.get("country") if isinstance(league, dict) else {}
        if not isinstance(country, dict):
            country = {}
        home = game_obj.get("homeTeam") or {}
        away = game_obj.get("awayTeam") or {}
        date_raw = (
            game_obj.get("date") or game_obj.get("startDate")
            or game_obj.get("dateUTC")
        )
        date_val: datetime | None = None
        if isinstance(date_raw, str):
            try:
                date_val = datetime.fromisoformat(
                    date_raw.replace("Z", "+00:00"),
                )
            except ValueError:
                date_val = None
        try:
            session.add(
                MatchResult(
                    game_id=int(gid),
                    date=date_val,
                    league_id=int(league.get("id") or 0) or None,
                    league_name=str(league.get("name") or "") or None,
                    country_name=str(country.get("name") or "") or None,
                    home_id=int(home.get("id"))
                    if isinstance(home, dict) and home.get("id") else None,
                    away_id=int(away.get("id"))
                    if isinstance(away, dict) and away.get("id") else None,
                    home_name=str(home.get("name") or "")
                    if isinstance(home, dict) else None,
                    away_name=str(away.get("name") or "")
                    if isinstance(away, dict) else None,
                    home_score=home_score,
                    away_score=away_score,
                    ingested_at=datetime.now(tz=UTC),
                )
            )
        except Exception as exc:  # pragma: no cover
            logger.debug("resolver: upsert MatchResult({}) failed: {}", gid, exc)
