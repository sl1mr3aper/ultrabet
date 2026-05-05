"""P1-11: предрасчёт прогнозов для топ-матчей следующих 24 ч.

Раз в 30 минут для ~50 самых значимых матчей запускается полный
конвейер `PredictionService.predict()` и результат кладётся в
in-mem кэш `_precomputed`. Хендлер прогнозов сначала проверяет этот
кэш: если совпало — отдаёт мгновенно, не дёргая SStats и ансамбль.

Это снижает нагрузку на 1–2 порядка при одновременных запросах
на одинаково популярные матчи (пример: дерби топ-5 лиги).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger


@dataclass(slots=True)
class PrecomputedEntry:
    game_id: int
    result: Any  # PredictionResult (не импортируем, чтобы избежать цикла)
    computed_at: datetime


class TopMatchesPrecompute:
    def __init__(
        self,
        sstats: Any,
        prediction_service_factory: Any,
        *,
        max_matches: int = 50,
        ttl_minutes: int = 30,
        session_factory: Any | None = None,
    ) -> None:
        self._sstats = sstats
        self._pf = prediction_service_factory
        self._max = max_matches
        self._ttl = timedelta(minutes=ttl_minutes)
        self._cache: dict[int, PrecomputedEntry] = {}
        # Опциональная запись системных прогнозов в PredictionOutcome —
        # даёт SelfLearner'у независимый поток данных для калибровки, не
        # завязанный на пользовательские запросы.
        self._session_factory = session_factory

    def get(self, game_id: int) -> Any | None:
        """Достать предрасчитанный результат если ещё свежий."""
        entry = self._cache.get(int(game_id))
        if entry is None:
            return None
        if datetime.now(tz=UTC) - entry.computed_at > self._ttl:
            self._cache.pop(int(game_id), None)
            return None
        return entry.result

    async def precompute_once(self) -> int:
        """Один проход: считает прогнозы для топ-матчей."""
        games = await self._collect_candidates()
        if not games:
            return 0
        pred_service = self._pf()
        done = 0
        for game_id in games[: self._max]:
            if game_id in self._cache:
                entry = self._cache[game_id]
                if datetime.now(tz=UTC) - entry.computed_at < self._ttl / 2:
                    continue
            try:
                result = await pred_service.predict(game_id)
            except Exception as exc:
                logger.debug("precompute: predict({}) error: {}", game_id, exc)
                continue
            if result is None:
                continue
            self._cache[int(game_id)] = PrecomputedEntry(
                game_id=int(game_id),
                result=result,
                computed_at=datetime.now(tz=UTC),
            )
            done += 1
            # P0-1/P0-2 feedback loop: записываем системный прогноз в
            # PredictionOutcome. SelfLearner позже сверит его с фактом.
            await self._record_outcome(result)
            # Между запросами — короткая пауза, чтобы не выедать квоту SStats.
            await asyncio.sleep(0.2)
        logger.info("TopMatchesPrecompute: обновлено {} прогнозов", done)
        return done

    async def _record_outcome(self, result: Any) -> None:
        """Пишет топ-10 рынков + все value-беты в PredictionOutcome.

        Более широкая выборка, чем раньше (было топ-3): нужна, чтобы
        SelfLearner имел достаточно данных для калибровки по разным
        рынкам, а также чтобы история прогнозов пользователей надёжнее
        получала hit/miss по главному прогнозу.

        Избегаем дубликатов: если в БД уже есть запись по этой паре
        (game_id, market_key), повторно не пишем.
        """
        if self._session_factory is None:
            return
        try:
            from sqlalchemy import select

            from db.models import PredictionOutcome
        except Exception:
            return
        try:
            odds_by_key: dict[str, float | None] = {
                getattr(vb, "market_key", ""): getattr(vb, "actual_odds", None)
                for vb in getattr(result, "value_bets", []) or []
                if getattr(vb, "market_key", None)
            }
            probs = getattr(result, "probabilities", None) or {}
            if not probs:
                return
            gid = int(getattr(result, "game_id", 0) or 0)
            if gid <= 0:
                return
            to_save: dict[str, float] = {}
            # Топ-10 по вероятности.
            for k, p in sorted(
                probs.items(), key=lambda kv: kv[1], reverse=True
            )[:10]:
                to_save[str(k)] = float(p)
            # Все value-беты — обязательно сохраняем вдобавок.
            for vb in getattr(result, "value_bets", None) or []:
                _vk = getattr(vb, "market_key", None)
                _vp = getattr(vb, "probability", None)
                if isinstance(_vk, str) and _vk and _vp is not None:
                    to_save.setdefault(_vk, float(_vp))
            if not to_save:
                return
            session = self._session_factory()
            try:
                existing_keys = set(
                    (
                        await session.scalars(
                            select(PredictionOutcome.market_key).where(
                                PredictionOutcome.game_id == gid,
                                PredictionOutcome.market_key.in_(list(to_save.keys())),
                            )
                        )
                    ).all()
                )
                added = 0
                for _mk, _pb in to_save.items():
                    if _mk in existing_keys:
                        continue
                    session.add(
                        PredictionOutcome(
                            game_id=gid,
                            market_key=_mk,
                            predicted_probability=_pb,
                            actual_odds=odds_by_key.get(_mk),
                        )
                    )
                    added += 1
                if added:
                    await session.commit()
            finally:
                await session.close()
        except Exception as exc:
            logger.debug("precompute record outcome: {}", exc)

    async def _collect_candidates(self) -> list[int]:
        """Возвращает упорядоченный список game_id топ-матчей.

        Простое правило: ближайшие 24 ч, с наибольшим престижем лиги.
        """
        from services.top_matches import LEAGUE_PRESTIGE
        horizon_start = datetime.now(tz=UTC)
        horizon_end = horizon_start + timedelta(hours=24)
        try:
            # Берём сегодня и завтра, агрегируем
            today = horizon_start.strftime("%Y-%m-%d")
            tomorrow = (horizon_start + timedelta(days=1)).strftime("%Y-%m-%d")
            games_today = await self._sstats.list_games(date=today, limit=120)
            games_tomorrow = await self._sstats.list_games(date=tomorrow, limit=120)
        except Exception as exc:
            logger.debug("precompute: list_games failed: {}", exc)
            return []
        all_games = (games_today or []) + (games_tomorrow or [])
        ranked: list[tuple[float, int]] = []
        for g in all_games:
            if not isinstance(g, dict):
                continue
            gid = g.get("id")
            if not gid:
                continue
            dt = _parse_dt(g)
            if dt is None or not (horizon_start <= dt <= horizon_end):
                continue
            league = g.get("league") or {}
            league_name = (
                league.get("name") if isinstance(league, dict) else ""
            ) or ""
            score = LEAGUE_PRESTIGE.get(league_name, 1.0)
            ranked.append((score, int(gid)))
        ranked.sort(key=lambda t: t[0], reverse=True)
        return [gid for _, gid in ranked]


def _parse_dt(g: dict[str, Any]) -> datetime | None:
    raw = g.get("date") or g.get("startDate") or g.get("dateUTC")
    if not isinstance(raw, str):
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt


__all__ = ["PrecomputedEntry", "TopMatchesPrecompute"]
