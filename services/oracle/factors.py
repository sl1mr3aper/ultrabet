"""Факторы Oracle: атомарные «оценщики» сигналов.

Каждая функция:
- получает на вход bundle (полный пакет данных от SStats) + контекст
  (probabilities, odds_map);
- возвращает :class:`FactorResult` со словарём сдвигов вероятностей
  по market_key и confidence ∈ [0, 1].

Сдвиги: положительные значения увеличивают вероятность, отрицательные —
уменьшают. Регулятор далее клампит и нормализует.

Все факторы — defensive: если данных недостаточно, возвращают пустой
shift и confidence=0 (не влияют на финальный результат).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from services.oracle.weights import MAX_FACTOR_DELTA


@dataclass(slots=True)
class FactorResult:
    name: str
    shifts: dict[str, float] = field(default_factory=dict)
    confidence: float = 0.0
    notes: list[str] = field(default_factory=list)

    @classmethod
    def empty(cls, name: str) -> FactorResult:
        return cls(name=name, shifts={}, confidence=0.0, notes=[])


def _clip_delta(value: float, scale: float = 1.0) -> float:
    cap = MAX_FACTOR_DELTA * scale
    return max(-cap, min(cap, value))


# ── Травмы ─────────────────────────────────────────────────────


def factor_injuries(
    bundle: dict[str, Any],
    *,
    home_id: int | None,
    away_id: int | None,
) -> FactorResult:
    """Чем больше травм у команды (особенно key players), тем хуже атака
    и защита. Реальные «стоимости» игроков SStats не отдаёт, поэтому
    считаем по числу травмированных. Приблизительный сдвиг:
    - 0–1 травм у команды → нет влияния
    - 2–3 травм → небольшое снижение исходных вероятностей этой команды
    - 4+ травм → значительное снижение
    """
    res = FactorResult.empty("injuries")
    injuries_raw = bundle.get("injuries") or []
    if not isinstance(injuries_raw, list) or not injuries_raw:
        return res
    home_count = 0
    away_count = 0
    for inj in injuries_raw:
        if not isinstance(inj, dict):
            continue
        team = inj.get("team") or inj.get("teamId") or {}
        if isinstance(team, dict):
            tid = team.get("id")
        else:
            tid = team
        try:
            tid_int = int(tid) if tid is not None else None
        except (TypeError, ValueError):
            tid_int = None
        if tid_int is None:
            continue
        if home_id is not None and tid_int == home_id:
            home_count += 1
        elif away_id is not None and tid_int == away_id:
            away_count += 1

    if home_count == 0 and away_count == 0:
        return res

    # Чем больше травм у команды, тем хуже её перспективы.
    # diff > 0 ⇒ у away больше травм ⇒ home выгоднее (+П1).
    diff = (away_count - home_count) * 0.005

    shifts = {
        "1": _clip_delta(diff, scale=1.0),
        "2": _clip_delta(-diff, scale=1.0),
        # Более травм у обеих команд → меньше голов в среднем
        "O25": _clip_delta(-(home_count + away_count) * 0.003),
        "U25": _clip_delta((home_count + away_count) * 0.003),
        "BTTS": _clip_delta(-(home_count + away_count) * 0.002),
        "BTTS_NO": _clip_delta((home_count + away_count) * 0.002),
    }
    confidence = min(1.0, (home_count + away_count) / 6.0)
    res.shifts = shifts
    res.confidence = confidence
    res.notes.append(f"home_inj={home_count} away_inj={away_count}")
    return res


# ── Форма команд ──────────────────────────────────────────────


def factor_form(bundle: dict[str, Any]) -> FactorResult:
    """Свежая форма по `last_games` блоку. SStats возвращает структуру с
    последними матчами обеих команд. Если у команды стрик > 3 побед или
    > 3 поражений, корректируем вероятности.
    """
    res = FactorResult.empty("form")
    lg = bundle.get("last_games")
    if not isinstance(lg, dict):
        return res
    home_form_pts = _form_points(lg.get("home") or lg.get("homeTeam"))
    away_form_pts = _form_points(lg.get("away") or lg.get("awayTeam"))
    if home_form_pts is None and away_form_pts is None:
        return res
    home_pts = home_form_pts or 0.0
    away_pts = away_form_pts or 0.0
    diff = home_pts - away_pts  # ∈ [-3, +3] примерно

    shift_home = _clip_delta(diff * 0.005)
    shifts = {
        "1": shift_home,
        "2": -shift_home,
        # Высокая форма → больше голов
        "O25": _clip_delta((home_pts + away_pts - 1.5) * 0.003),
        "BTTS": _clip_delta((home_pts + away_pts - 1.5) * 0.002),
    }
    confidence = min(1.0, abs(diff) / 3.0)
    res.shifts = shifts
    res.confidence = confidence
    res.notes.append(f"home_pts={home_pts:.2f} away_pts={away_pts:.2f}")
    return res


def _form_points(team_block: Any) -> float | None:
    """Среднее очков за матч по последним N матчам команды.

    SStats отдаёт `last_games` в нескольких возможных форматах. Мы
    защитно ищем поля `wins`, `draws`, `losses` или `last_5_form`.
    """
    if not isinstance(team_block, dict):
        return None
    # Вариант 1: явные счётчики
    wins = team_block.get("wins")
    draws = team_block.get("draws")
    losses = team_block.get("losses")
    if isinstance(wins, int) and isinstance(draws, int) and isinstance(losses, int):
        total = wins + draws + losses
        if total > 0:
            return (wins * 3 + draws) / total
    # Вариант 2: строка вида "WWDLW"
    form_str = team_block.get("form") or team_block.get("last5")
    if isinstance(form_str, str) and form_str:
        pts = 0.0
        n = 0
        for ch in form_str.upper():
            if ch == "W":
                pts += 3
                n += 1
            elif ch == "D":
                pts += 1
                n += 1
            elif ch == "L":
                n += 1
        if n > 0:
            return pts / n
    return None


# ── Мотивация по таблице ──────────────────────────────────────


def factor_motivation(
    bundle: dict[str, Any],
    *,
    home_id: int | None,
    away_id: int | None,
) -> FactorResult:
    """Мотивация по `season_table`. Если команда борется:
    - за чемпионство (top-1 / top-2) — +0.5..1 п.п. к её победе
    - за зону еврокубков (3..6 место в зависимости от лиги) — +
    - против вылета (последние 3 строки) — +
    Спокойная середина — нейтрально.
    """
    res = FactorResult.empty("motivation")
    table_raw = bundle.get("season_table")
    rows: list[dict[str, Any]] = []
    if isinstance(table_raw, dict):
        if isinstance(table_raw.get("rows"), list):
            rows = [r for r in table_raw["rows"] if isinstance(r, dict)]
        elif isinstance(table_raw.get("table"), list):
            rows = [r for r in table_raw["table"] if isinstance(r, dict)]
    elif isinstance(table_raw, list):
        rows = [r for r in table_raw if isinstance(r, dict)]
    if not rows:
        return res

    def _pos_for(team_id: int | None) -> tuple[int, int] | None:
        if team_id is None:
            return None
        for r in rows:
            t = r.get("team") or {}
            tid = t.get("id") if isinstance(t, dict) else r.get("teamId")
            try:
                tid_int = int(tid) if tid is not None else None
            except (TypeError, ValueError):
                tid_int = None
            if tid_int == team_id:
                pos_raw = r.get("position") or r.get("rank") or r.get("place")
                try:
                    pos = int(pos_raw)
                except (TypeError, ValueError):
                    return None
                return pos, len(rows)
        return None

    home_pos = _pos_for(home_id)
    away_pos = _pos_for(away_id)
    if home_pos is None and away_pos is None:
        return res

    home_boost = _motivation_boost(home_pos)
    away_boost = _motivation_boost(away_pos)
    diff = home_boost - away_boost

    shift_home = _clip_delta(diff * 0.005)
    res.shifts = {
        "1": shift_home,
        "2": -shift_home,
    }
    res.confidence = min(1.0, abs(diff) / 2.0)
    res.notes.append(f"home_pos={home_pos} away_pos={away_pos}")
    return res


def _motivation_boost(pos_total: tuple[int, int] | None) -> float:
    """Возвращает «уровень мотивации» команды по её позиции."""
    if pos_total is None:
        return 0.0
    pos, total = pos_total
    if total <= 0:
        return 0.0
    if pos <= 2:
        # Борьба за чемпионство
        return 1.0
    if pos <= max(4, int(total * 0.3)):
        # Еврокубки
        return 0.7
    if pos >= total - 2:
        # Зона вылета — мотивация максимальная
        return 1.0
    if pos >= total - max(4, int(total * 0.3)):
        # Около зоны вылета
        return 0.6
    # Спокойная середина
    return 0.0


# ── H2H + «Профи-грузы» ───────────────────────────────────────


def factor_h2h_profits(
    bundle: dict[str, Any],
    *,
    home_id: int | None,
    away_id: int | None,
) -> FactorResult:
    """SStats `/Games/profits` отдаёт «грузы» — какие исходы заходили
    у этих команд в последних N матчах в этой лиге. Если у home в
    последних 25 матчах в лиге `over_2.5` заходило 80% — это сильный
    сигнал.
    """
    res = FactorResult.empty("h2h_profits")
    profits = bundle.get("profits")
    if not isinstance(profits, dict):
        return res
    # Структура profits может быть {home: [{market, hits, total, roi}, ...], away: [...]}
    home_block = profits.get("home") or profits.get("homeTeam")
    away_block = profits.get("away") or profits.get("awayTeam")
    shifts: dict[str, float] = {}
    notes: list[str] = []
    confidence = 0.0
    for team_block, side_label in (
        (home_block, "home"),
        (away_block, "away"),
    ):
        if not isinstance(team_block, list):
            continue
        for item in team_block:
            if not isinstance(item, dict):
                continue
            market_key = (
                item.get("market_key")
                or item.get("marketKey")
                or item.get("market")
            )
            if not isinstance(market_key, str):
                continue
            hits = item.get("hits") or item.get("wins") or 0
            total = item.get("total") or item.get("count") or 0
            try:
                hits_i = int(hits)
                total_i = int(total)
            except (TypeError, ValueError):
                continue
            if total_i < 5:
                continue
            ratio = hits_i / total_i
            # Если ratio > 0.7 → small boost; если < 0.3 → small penalty
            delta = (ratio - 0.5) * 0.04  # ±2 п.п. макс при 100%/0%
            shifts[market_key] = shifts.get(market_key, 0.0) + _clip_delta(
                delta, scale=0.5
            )
            confidence = max(confidence, min(1.0, total_i / 25.0))
            notes.append(f"{side_label}:{market_key}={hits_i}/{total_i}")
    res.shifts = shifts
    res.confidence = confidence
    res.notes = notes[:8]
    return res


# ── Рыночные «грузы»: расхождение модели и букмекеров ─────────


def factor_market_drift(
    *,
    probabilities: dict[str, float],
    odds_map: dict[str, float],
) -> FactorResult:
    """Если букмекеры (consensus) сильно расходятся с нашей моделью —
    добавляем небольшой сдвиг в сторону рынка. Это страховка от системных
    ошибок ансамбля. Применяем только при значительном расхождении (>5 п.п.)
    и только небольшим долом (≤30%).
    """
    res = FactorResult.empty("market_drift")
    if not probabilities or not odds_map:
        return res
    shifts: dict[str, float] = {}
    used = 0
    total = 0
    for key, prob in probabilities.items():
        odds = odds_map.get(key)
        if not isinstance(odds, (int, float)) or odds <= 1.0:
            continue
        total += 1
        implied = 1.0 / odds
        gap = implied - prob
        if abs(gap) < 0.05:
            continue
        # Сдвигаем модель на 30% от gap, но не более ±MAX_FACTOR_DELTA
        shift = _clip_delta(gap * 0.3, scale=1.0)
        shifts[key] = shift
        used += 1
    if used == 0:
        return res
    res.shifts = shifts
    res.confidence = min(1.0, used / max(5.0, total / 2.0))
    res.notes.append(f"used={used}/{total}")
    return res


__all__ = [
    "FactorResult",
    "factor_form",
    "factor_h2h_profits",
    "factor_injuries",
    "factor_market_drift",
    "factor_motivation",
]
