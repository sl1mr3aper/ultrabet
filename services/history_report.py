"""Подготовка истории прогнозов пользователя для UI и xlsx-выгрузки.

Логика:
- Берём все `PredictionLog` пользователя.
- Дедуплицируем по `(game_id, market_key)` — оставляем самый свежий.
- По каждому прогнозу подтягиваем `PredictionOutcome` (hit).
- Прибыль/убыток считаем в условных юнитах от *fair-кфа* (1 / p), а не от
  букмекерского коэфа: пользователь явно попросил не показывать нигде
  букмекерские кф, только то, что считается по формулам.

Используется в `bot/handlers/history.py` (страничная история и отчёты).
"""

from __future__ import annotations

import io
import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from db.models import MatchResult, PredictionLog, PredictionOutcome


@dataclass(slots=True)
class HistoryRow:
    """Одна запись истории — уже с подтянутым исходом и подсчитанной прибылью."""

    log_id: int
    created_at: datetime
    game_id: int
    home: str
    away: str
    league: str | None
    market_key: str | None
    market_label: str | None
    model_prob: float | None
    fair_odd: float | None  # 1 / p, ограничен диапазоном [1.05; 30]
    hit: bool | None
    profit: float  # в юнитах ставки (ставка = 1 у.е., считаем по fair-кфу)
    home_score: int | None = None
    away_score: int | None = None


def _parse_payload(payload: str | None) -> dict[str, Any]:
    if not payload:
        return {}
    try:
        data = json.loads(payload)
    except (ValueError, TypeError):
        return {}
    return data if isinstance(data, dict) else {}


def _fair_odd(prob: float | None) -> float | None:
    """Fair-кф = 1 / p. Возвращаем `None`, если результат вне разумного диапазона."""
    if prob is None or prob <= 0.0 or prob >= 1.0:
        return None
    fo = 1.0 / prob
    if fo < 1.05 or fo > 30.0:
        return None
    return round(fo + 1e-9, 2)


def _profit_for(hit: bool | None, fair_odd: float | None) -> float:
    """Прибыль в юнитах за ставку 1 у.е. по *fair-кфу*.

    - Прогноз сыграл (hit=True): прибыль = (fair_odd − 1).
      Если fair_odd неизвестен — 0 (нечего считать).
    - Прогноз не сыграл (hit=False): убыток = −1.
    - Pending (hit is None): 0.
    """
    if hit is True:
        if isinstance(fair_odd, (int, float)) and fair_odd > 1.0:
            return float(fair_odd) - 1.0
        return 0.0
    if hit is False:
        return -1.0
    return 0.0


async def collect_history(
    session: AsyncSession, user_id: int,
) -> list[HistoryRow]:
    """Все прогнозы пользователя в порядке убывания даты, без дублей."""

    logs_q = await session.scalars(
        select(PredictionLog)
        .where(PredictionLog.user_id == user_id)
        .order_by(PredictionLog.created_at.desc())
    )
    logs = list(logs_q)
    if not logs:
        return []

    # Дедуп по (game_id, market_key). Так как сортировка `desc`, первый
    # увиденный — самый свежий, его и оставляем.
    seen: set[tuple[int, str]] = set()
    keep: list[PredictionLog] = []
    for r in logs:
        payload = _parse_payload(r.payload)
        market_key = payload.get("top_market_key") or ""
        dedup_key = (r.game_id, str(market_key))
        if dedup_key in seen:
            continue
        seen.add(dedup_key)
        keep.append(r)

    game_ids = sorted({r.game_id for r in keep})
    outcomes_map: dict[tuple[int, str], PredictionOutcome] = {}
    scores_map: dict[int, tuple[int, int]] = {}
    if game_ids:
        out_q = await session.scalars(
            select(PredictionOutcome).where(
                PredictionOutcome.game_id.in_(game_ids),
            )
        )
        for o in out_q:
            outcomes_map[(o.game_id, o.market_key)] = o
        # Счёт из MatchResult — для показа в UI/xlsx.
        mr_q = await session.scalars(
            select(MatchResult).where(MatchResult.game_id.in_(game_ids))
        )
        for mr in mr_q:
            if mr.home_score is not None and mr.away_score is not None:
                scores_map[mr.game_id] = (mr.home_score, mr.away_score)

    rows: list[HistoryRow] = []
    for r in keep:
        payload = _parse_payload(r.payload)
        market_key = payload.get("top_market_key") or None
        market_label = payload.get("top_label") or None
        model_prob = payload.get("top_prob")
        if not isinstance(model_prob, (int, float)):
            model_prob = None
        else:
            model_prob = float(model_prob)

        hit: bool | None = None
        if market_key:
            outcome = outcomes_map.get((r.game_id, str(market_key)))
            if outcome is not None:
                hit = outcome.hit

        fair_odd = _fair_odd(model_prob)
        sc = scores_map.get(r.game_id)
        rows.append(
            HistoryRow(
                log_id=r.id,
                created_at=r.created_at,
                game_id=r.game_id,
                home=r.home_name,
                away=r.away_name,
                league=r.league_name,
                market_key=str(market_key) if market_key else None,
                market_label=market_label,
                model_prob=model_prob,
                fair_odd=fair_odd,
                hit=hit,
                profit=_profit_for(hit, fair_odd),
                home_score=sc[0] if sc else None,
                away_score=sc[1] if sc else None,
            )
        )

    return rows


def filter_by_period(
    rows: list[HistoryRow], *, days: int | None,
) -> list[HistoryRow]:
    """Оставляет прогнозы за последние N дней (None = все)."""
    if days is None:
        return list(rows)
    cutoff = datetime.now(tz=UTC) - timedelta(days=days)
    out: list[HistoryRow] = []
    for r in rows:
        ts = r.created_at
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=UTC)
        if ts >= cutoff:
            out.append(r)
    return out


def _hit_label(hit: bool | None) -> str:
    if hit is True:
        return "сыграл"
    if hit is False:
        return "не сыграл"
    return "ждём"


def render_xlsx(rows: list[HistoryRow], *, title: str) -> bytes:
    """Сгенерировать xlsx-отчёт по истории прогнозов.

    Колонки:
    - Дата (UTC)
    - Лига, Хозяева, Гости
    - Прогноз (текстовая метка рынка)
    - Вероятность модели (%)
    - Fair-кф (1 / p) — это и есть «коэф по формуле», без букмекерок
    - Исход
    - Прибыль (у.е.) — считается по fair-кфу
    """

    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "Прогнозы"

    headers = [
        "Дата (UTC)",
        "Лига",
        "Хозяева",
        "Гости",
        "Счёт",
        "Прогноз",
        "Вероятность модели",
        "Кф по формуле (fair)",
        "Исход",
        "Прибыль (у.е.)",
    ]
    ws.append(headers)
    head_fill = PatternFill("solid", fgColor="1F4E78")
    head_font = Font(bold=True, color="FFFFFF")
    for col_idx in range(1, len(headers) + 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.fill = head_fill
        cell.font = head_font
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for r in rows:
        score_cell = (
            f"{r.home_score}:{r.away_score}"
            if r.home_score is not None and r.away_score is not None
            else "—"
        )
        ws.append(
            [
                r.created_at.strftime("%Y-%m-%d %H:%M"),
                r.league or "",
                r.home,
                r.away,
                score_cell,
                r.market_label or r.market_key or "",
                f"{r.model_prob * 100:.1f}%" if r.model_prob is not None else "",
                f"{r.fair_odd:.2f}" if r.fair_odd is not None else "",
                _hit_label(r.hit),
                round(r.profit, 2),
            ]
        )

    hits = sum(1 for r in rows if r.hit is True)
    misses = sum(1 for r in rows if r.hit is False)
    pending = sum(1 for r in rows if r.hit is None)
    resolved = hits + misses
    hit_rate = (hits / resolved * 100.0) if resolved else 0.0
    total_profit = round(sum(r.profit for r in rows), 2)
    roi = (total_profit / resolved * 100.0) if resolved else 0.0

    ws.append([])
    summary_row = ws.max_row + 1
    summary = [
        ("Отчёт", title),
        ("Всего прогнозов", len(rows)),
        ("Сыграло", hits),
        ("Не сыграло", misses),
        ("Ждём результата", pending),
        ("Hit-rate (по решённым)", f"{hit_rate:.1f}%"),
        ("Прибыль за период (у.е.)", total_profit),
        ("ROI (по решённым)", f"{roi:.1f}%"),
    ]
    for label, value in summary:
        ws.append([label, value])
    bold = Font(bold=True)
    for i in range(len(summary)):
        ws.cell(row=summary_row + i, column=1).font = bold

    widths = [18, 28, 22, 22, 10, 28, 18, 14, 14, 16]
    from openpyxl.utils import get_column_letter
    for i, w in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


__all__ = [
    "HistoryRow",
    "collect_history",
    "filter_by_period",
    "render_xlsx",
]
