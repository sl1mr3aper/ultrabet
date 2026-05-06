"""P0-8: Closing Line Value tracker (Betfair).

Зачем: единственная индустрия-стандартная метрика "обыгрываем ли мы рынок"
— это CLV = ``prob_model × close_odds - 1``. Без неё любой ROI < 5% — шум.

Архитектура:

1. ``BetfairMarketResolver`` — находит Betfair market_id для пары
   (event, market_type) по локальному соответствию (handcrafted dict
   на старте; в проде заменить на полноценный resolver через
   ``listMarketCatalogue`` + fuzzy match команд).
2. ``ClvTracker`` — основной сервис:
   - ``capture_for_pick(outcome)`` — снимает closing-odds для одного пика
     и записывает в ``PinnacleClosingOdds`` + обновляет
     ``PredictionOutcome.closing_odds`` / ``.clv``.
   - ``capture_pending_closes(...)`` — находит все pending пики, у
     которых матч стартует в ближайшие N минут, и снимает по ним.
   - ``aggregate_clv(period_days, league_id=None, market_key=None)`` —
     возвращает агрегированный CLV (avg, median, hit-rate>0).
3. ``run_clv_capture_loop(...)`` — fire-and-forget loop, кладётся в
   `_services` startup-tasks. Ходит каждые 60 сек, ищет матчи в
   t-15..t-3 минут и снимает по ним closing odds.

Ограничения этого скелета:
- Mapping {SStats game_id → Betfair event_id} статический (заглушка).
  В проде — отдельный сервис ``services.event_matcher`` с fuzzy
  matching по командам и датам.
- Snap делается одной точкой во времени (не tracking line moves).
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from loguru import logger
from sqlalchemy import and_, case, func, select

from db.models import PinnacleClosingOdds, PredictionOutcome
from services.betfair_client import BetfairClient

# ─── Резолвер market-id ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class BetfairMarketRef:
    """Ссылка на конкретный (market_id, runner_selection_id) Betfair."""

    market_id: str
    selection_id: int
    market_type: str  # "MATCH_ODDS" | "OVER_UNDER_25" | "BTTS" и т.д.


class _BetfairMarketResolverProtocol(Protocol):
    """Минимальный протокол: ``resolve(game_id, market_key) -> ref|None``."""

    async def resolve(
        self, *, game_id: int, market_key: str
    ) -> BetfairMarketRef | None: ...


class StaticBetfairMarketResolver:
    """In-memory резолвер: маппинг ``(game_id, market_key) -> BetfairMarketRef``.

    Используется для тестов и ручного maintenance-режима. В проде
    замени на ``DynamicBetfairMarketResolver``, который ищет market через
    `listMarketCatalogue` по названиям команд.
    """

    def __init__(
        self, mapping: dict[tuple[int, str], BetfairMarketRef] | None = None
    ) -> None:
        self._mapping: dict[tuple[int, str], BetfairMarketRef] = dict(
            mapping or {}
        )

    def add(
        self, *, game_id: int, market_key: str, ref: BetfairMarketRef
    ) -> None:
        self._mapping[(game_id, market_key)] = ref

    async def resolve(
        self, *, game_id: int, market_key: str
    ) -> BetfairMarketRef | None:
        return self._mapping.get((game_id, market_key))


# ─── Динамический резолвер через listMarketCatalogue ────────────────────────


# Маппинг наших market_key → Betfair marketTypeCode + selection-name pattern.
# Selection-name берётся из runner.runnerName (обычно "Team A", "Team B",
# "The Draw", "Over 2.5", "Under 2.5", "Yes" / "No").
@dataclass(frozen=True)
class _BetfairMarketSpec:
    market_type: str  # MATCH_ODDS / OVER_UNDER_25 / BOTH_TEAMS_TO_SCORE
    selection_name_for: str  # "home" | "away" | "draw" | literal


_MARKET_KEY_SPECS: dict[str, _BetfairMarketSpec] = {
    # Двухсторонний (1×2)
    "1": _BetfairMarketSpec("MATCH_ODDS", "home"),
    "X": _BetfairMarketSpec("MATCH_ODDS", "The Draw"),
    "2": _BetfairMarketSpec("MATCH_ODDS", "away"),
    # Total goals 2.5
    "tover_2.5": _BetfairMarketSpec("OVER_UNDER_25", "Over 2.5 Goals"),
    "tunder_2.5": _BetfairMarketSpec("OVER_UNDER_25", "Under 2.5 Goals"),
    # BTTS
    "btts_yes": _BetfairMarketSpec("BOTH_TEAMS_TO_SCORE", "Yes"),
    "btts_no": _BetfairMarketSpec("BOTH_TEAMS_TO_SCORE", "No"),
}


class DynamicBetfairMarketResolver:
    """Резолвит ``(game_id, market_key)`` в ``BetfairMarketRef`` через
    ``listEvents`` + ``listMarketCatalogue``.

    Зависит от внешнего ``match_lookup``: ``Callable[[game_id],
    Awaitable[tuple[home, away, start_dt] | None]]`` — обычно идёт в БД
    к таблице ``match_pick_history`` или ``predictions`` за этой инфой.

    Кэширует event_id и market_id LRU-словарём (по умолчанию 4096
    записей), чтобы не дёргать API повторно.
    """

    def __init__(
        self,
        *,
        betfair: BetfairClient,
        match_lookup: Any,  # callable async
        soccer_event_type_id: str = "1",
        time_window_hours: int = 6,
    ) -> None:
        from services.betfair_client import BetfairClient as _BFC

        if not isinstance(betfair, _BFC):
            raise TypeError("betfair must be BetfairClient instance")
        self._betfair = betfair
        self._match_lookup = match_lookup
        self._sport_id = soccer_event_type_id
        self._time_window_hours = max(1, int(time_window_hours))
        self._event_cache: dict[int, str] = {}
        self._market_cache: dict[tuple[str, str], BetfairMarketRef] = {}

    async def resolve(
        self, *, game_id: int, market_key: str
    ) -> BetfairMarketRef | None:
        spec = _MARKET_KEY_SPECS.get(market_key)
        if spec is None:
            return None

        event_id = await self._find_event_id(game_id)
        if event_id is None:
            return None

        cache_key = (event_id, spec.market_type)
        if cache_key not in self._market_cache:
            ref = await self._fetch_market_ref(event_id, spec)
            if ref is None:
                return None
            self._market_cache[cache_key] = ref

        cached = self._market_cache[cache_key]
        # Для MATCH_ODDS у нас 3 selection: home, away, draw. У cached
        # сохранили MATCH_ODDS, но selection_id мог быть от любой стороны.
        # Поэтому при 1×2 надо найти конкретно home/away/draw selection.
        if spec.market_type == "MATCH_ODDS":
            ref = await self._resolve_1x2_selection(
                game_id=game_id, event_id=event_id, market_id=cached.market_id, spec=spec
            )
            if ref is not None:
                self._market_cache[cache_key] = ref  # обновляем кэш
                return ref
            return None

        return cached

    async def _find_event_id(self, game_id: int) -> str | None:
        if game_id in self._event_cache:
            return self._event_cache[game_id]

        info = await self._match_lookup(game_id)
        if info is None:
            return None
        home, away, start_dt = info
        if not isinstance(start_dt, datetime):
            return None

        # listEvents с textQuery (Betfair умеет fuzzy по обоим сторонам)
        from_dt = (start_dt - timedelta(hours=self._time_window_hours)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        to_dt = (start_dt + timedelta(hours=self._time_window_hours)).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )

        try:
            events = await self._betfair.list_events(
                event_type_ids=[self._sport_id],
                market_start_time={"from": from_dt, "to": to_dt},
                text_query=f"{home} {away}",
            )
        except Exception as exc:  # pragma: no cover - сетевой fallback
            logger.debug("Betfair listEvents failed: {}", exc)
            return None

        if not events:
            return None

        # events: [{"event": {"id": ..., "name": ...}, "marketCount": N}]
        event_id = self._best_event_match(events, home=home, away=away)
        if event_id is None:
            return None
        self._event_cache[game_id] = event_id
        return event_id

    @staticmethod
    def _best_event_match(
        events: list[dict[str, Any]], *, home: str, away: str
    ) -> str | None:
        home_l = home.lower()
        away_l = away.lower()
        best: tuple[int, str] | None = None
        for entry in events:
            ev = entry.get("event") or {}
            name = str(ev.get("name") or "").lower()
            ev_id = ev.get("id")
            if not ev_id:
                continue
            score = 0
            if home_l in name:
                score += 1
            if away_l in name:
                score += 1
            if score == 0:
                continue
            if best is None or score > best[0]:
                best = (score, str(ev_id))
        return best[1] if best else None

    async def _fetch_market_ref(
        self, event_id: str, spec: _BetfairMarketSpec
    ) -> BetfairMarketRef | None:
        try:
            catalogue = await self._betfair.list_market_catalogue(
                event_ids=[event_id],
                market_type_codes=[spec.market_type],
                market_projection=["RUNNER_DESCRIPTION"],
                max_results=10,
            )
        except Exception as exc:  # pragma: no cover - сетевой fallback
            logger.debug("Betfair listMarketCatalogue failed: {}", exc)
            return None
        if not catalogue:
            return None
        # Берём первый matching market этого типа (обычно он один на event)
        market = catalogue[0]
        market_id = str(market.get("marketId") or "")
        runners = market.get("runners") or []
        if not market_id or not runners:
            return None
        # Для не-1×2 рынков (over/under, btts) selection ищем по имени
        if spec.market_type == "MATCH_ODDS":
            # Заглушка — конкретный selection подставит resolver_1x2 ниже
            return BetfairMarketRef(
                market_id=market_id,
                selection_id=int(runners[0].get("selectionId") or 0),
                market_type=spec.market_type,
            )
        # Прямой матч имени в OVER_UNDER_25 / BTTS:
        target = spec.selection_name_for.lower()
        for runner in runners:
            name = str(runner.get("runnerName") or "").lower()
            if name == target:
                return BetfairMarketRef(
                    market_id=market_id,
                    selection_id=int(runner.get("selectionId") or 0),
                    market_type=spec.market_type,
                )
        return None

    async def _resolve_1x2_selection(
        self,
        *,
        game_id: int,
        event_id: str,
        market_id: str,
        spec: _BetfairMarketSpec,
    ) -> BetfairMarketRef | None:
        info = await self._match_lookup(game_id)
        if info is None:
            return None
        home, away, _ = info

        try:
            catalogue = await self._betfair.list_market_catalogue(
                event_ids=[event_id],
                market_type_codes=["MATCH_ODDS"],
                market_projection=["RUNNER_DESCRIPTION"],
                max_results=5,
            )
        except Exception as exc:  # pragma: no cover
            logger.debug("Betfair listMarketCatalogue (1x2) failed: {}", exc)
            return None
        if not catalogue:
            return None
        market = next(
            (m for m in catalogue if str(m.get("marketId") or "") == market_id),
            catalogue[0],
        )
        runners = market.get("runners") or []

        # selection_name_for: "home" | "away" | "The Draw"
        selection_target: str | None
        if spec.selection_name_for == "home":
            selection_target = home
        elif spec.selection_name_for == "away":
            selection_target = away
        else:
            selection_target = spec.selection_name_for

        if selection_target is None:
            return None
        target = selection_target.lower()
        for runner in runners:
            name = str(runner.get("runnerName") or "").lower()
            if name == target or target in name or name in target:
                return BetfairMarketRef(
                    market_id=str(market.get("marketId") or ""),
                    selection_id=int(runner.get("selectionId") or 0),
                    market_type=spec.market_type,
                )
        return None


# ─── Основной сервис ────────────────────────────────────────────────────────


@dataclass(slots=True)
class CapturedClose:
    game_id: int
    market_key: str
    closing_odds: float
    captured_at: datetime
    clv: float | None  # None, если у нас нет predicted_probability


def compute_clv(
    *, predicted_prob: float | None, closing_odds: float | None
) -> float | None:
    """CLV = prob × close_odds − 1.

    Возвращает None, если хоть один из аргументов None или close_odds<=1.
    """
    if predicted_prob is None or closing_odds is None:
        return None
    if closing_odds <= 1.0 or predicted_prob <= 0.0 or predicted_prob > 1.0:
        return None
    return predicted_prob * closing_odds - 1.0


class ClvTracker:
    """Фасад над снятием closing odds и записью CLV.

    Параметры:
    - ``session_factory`` — асинхронная фабрика SQLAlchemy сессий
      (например ``database.session``).
    - ``betfair`` — авторизованный ``BetfairClient``.
    - ``resolver`` — реализация ``_BetfairMarketResolverProtocol``.
    """

    def __init__(
        self,
        *,
        session_factory: Any,
        betfair: BetfairClient,
        resolver: _BetfairMarketResolverProtocol,
    ) -> None:
        self._session_factory = session_factory
        self._betfair = betfair
        self._resolver = resolver

    # ── single-pick ─────────────────────────────────────────────────────

    async def capture_for_pick(
        self, outcome: PredictionOutcome
    ) -> CapturedClose | None:
        """Снимает closing-odds для одного пика. Возвращает None, если

        * нет mapping в Betfair, или
        * Betfair вернул пустой ответ.
        """
        ref = await self._resolver.resolve(
            game_id=outcome.game_id, market_key=outcome.market_key
        )
        if ref is None:
            logger.debug(
                "CLV: нет Betfair-mapping для game={} market={}",
                outcome.game_id, outcome.market_key,
            )
            return None
        books = await self._betfair.list_market_book(
            [ref.market_id],
            price_projection={"priceData": ["EX_BEST_OFFERS"]},
        )
        if not books:
            return None
        runners = books[0].get("runners") or []
        runner = next(
            (r for r in runners if r.get("selectionId") == ref.selection_id),
            None,
        )
        if runner is None:
            return None
        # lastPriceTraded — последняя проторгованная цена (LPT) — самая
        # точная аппроксимация closing odds; если нет, берём best back.
        close = runner.get("lastPriceTraded")
        if close is None:
            best_back = (
                runner.get("ex", {}).get("availableToBack") or [{}]
            )
            close = (best_back[0] or {}).get("price")
        if close is None:
            return None
        try:
            close_f = float(close)
        except (TypeError, ValueError):
            return None
        clv = compute_clv(
            predicted_prob=outcome.predicted_probability,
            closing_odds=close_f,
        )
        captured = CapturedClose(
            game_id=outcome.game_id,
            market_key=outcome.market_key,
            closing_odds=close_f,
            captured_at=datetime.now(tz=UTC),
            clv=clv,
        )
        await self._persist(outcome, captured)
        return captured

    async def _persist(
        self,
        outcome: PredictionOutcome,
        captured: CapturedClose,
    ) -> None:
        async with self._session_factory() as session:
            # 1. Snapshot в pinnacle_closing_odds (исторический лог).
            session.add(
                PinnacleClosingOdds(
                    game_id=captured.game_id,
                    market_key=captured.market_key,
                    closing_odds=captured.closing_odds,
                    captured_at=captured.captured_at,
                )
            )
            # 2. Подтягиваем самую "свежую" запись PredictionOutcome
            #    для этой пары и обновляем closing_odds + clv.
            stmt = (
                select(PredictionOutcome)
                .where(
                    and_(
                        PredictionOutcome.game_id == outcome.game_id,
                        PredictionOutcome.market_key == outcome.market_key,
                    )
                )
                .order_by(PredictionOutcome.id.desc())
                .limit(1)
            )
            res = await session.execute(stmt)
            latest = res.scalar_one_or_none()
            if latest is not None:
                latest.closing_odds = captured.closing_odds
                latest.clv = captured.clv
            await session.commit()

    # ── bulk ────────────────────────────────────────────────────────────

    async def capture_pending_closes(
        self,
        *,
        outcomes: Sequence[PredictionOutcome],
        concurrency: int = 4,
    ) -> list[CapturedClose]:
        """Снимает закрытие для пачки пиков, ограниченно параллельно."""
        sem = asyncio.Semaphore(concurrency)
        results: list[CapturedClose] = []

        async def _one(o: PredictionOutcome) -> None:
            async with sem:
                try:
                    cap = await self.capture_for_pick(o)
                except Exception as exc:
                    logger.warning(
                        "CLV: capture failed game={} market={}: {}",
                        o.game_id, o.market_key, exc,
                    )
                    return
                if cap is not None:
                    results.append(cap)

        await asyncio.gather(*(_one(o) for o in outcomes))
        return results

    # ── aggregate ───────────────────────────────────────────────────────

    async def aggregate_clv(
        self,
        *,
        period_days: int = 30,
        league_id: int | None = None,
        market_key: str | None = None,
    ) -> dict[str, Any]:
        """Считает агрегированную CLV-метрику за последние N дней."""
        since = datetime.now(tz=UTC) - timedelta(days=period_days)
        async with self._session_factory() as session:
            stmt = select(
                func.count().label("total"),
                func.avg(PredictionOutcome.clv).label("avg_clv"),
                func.sum(
                    case(
                        (PredictionOutcome.clv > 0, 1),
                        else_=0,
                    )
                ).label("positive_clv"),
            ).where(
                and_(
                    PredictionOutcome.created_at >= since,
                    PredictionOutcome.clv.is_not(None),
                )
            )
            if league_id is not None:
                stmt = stmt.where(PredictionOutcome.league_id == league_id)
            if market_key is not None:
                stmt = stmt.where(PredictionOutcome.market_key == market_key)
            row = (await session.execute(stmt)).one()
        total = int(row.total or 0)
        positive = int(row.positive_clv or 0)
        return {
            "period_days": period_days,
            "league_id": league_id,
            "market_key": market_key,
            "n_picks": total,
            "avg_clv": float(row.avg_clv) if row.avg_clv is not None else None,
            "positive_clv_rate": (
                positive / total if total > 0 else None
            ),
        }


# ─── фоновый loop ───────────────────────────────────────────────────────────


async def fetch_pending_pre_match(
    *,
    session_factory: Any,
    minutes_before_kickoff: tuple[int, int] = (3, 15),
) -> list[PredictionOutcome]:
    """Возвращает PredictionOutcome'ы, у которых матч стартует через
    ``min..max`` минут и closing_odds ещё не зафиксирован.

    Match start time мы НЕ храним напрямую в PredictionOutcome — поэтому
    в этом скелете возвращаем все pending без closing_odds, оставляя
    интеграцию со scheduler'ом матчей на следующий шаг.
    """
    _ = minutes_before_kickoff  # placeholder для будущей интеграции
    async with session_factory() as session:
        stmt = (
            select(PredictionOutcome)
            .where(PredictionOutcome.closing_odds.is_(None))
            .order_by(PredictionOutcome.id.desc())
            .limit(50)
        )
        res = await session.execute(stmt)
        return list(res.scalars().all())


async def _iter_loop_ticks(interval_seconds: float) -> AsyncIterator[None]:
    while True:
        yield None
        await asyncio.sleep(interval_seconds)


async def run_clv_capture_loop(
    *,
    tracker: ClvTracker,
    session_factory: Any,
    interval_seconds: float = 60.0,
) -> None:
    """Фоновый цикл: каждые ``interval_seconds`` снимает closing odds
    для pending-пиков. Подключается из main.py как long-running task.

    В этом скелете loop не пытается фильтровать по времени до старта
    матча — это войдёт в следующую итерацию (см. fetch_pending_pre_match).
    """
    logger.info("CLV capture loop started (every {}s)", interval_seconds)
    async for _ in _iter_loop_ticks(interval_seconds):
        try:
            outcomes = await fetch_pending_pre_match(
                session_factory=session_factory
            )
            if not outcomes:
                continue
            captured = await tracker.capture_pending_closes(outcomes=outcomes)
            if captured:
                logger.info("CLV: captured {} closing odds", len(captured))
        except Exception as exc:
            logger.warning("CLV loop: {}", exc)


__all__ = [
    "BetfairMarketRef",
    "CapturedClose",
    "ClvTracker",
    "DynamicBetfairMarketResolver",
    "StaticBetfairMarketResolver",
    "compute_clv",
    "fetch_pending_pre_match",
    "run_clv_capture_loop",
]
