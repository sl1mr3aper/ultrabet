"""Корректировки точности на основе дополнительных данных SStats.

Принимает бундл из `SStatsClient.get_full_match_data()` и возвращает
поправки к рейтингам и xG. Цель — учесть факторы, которые сами по себе
Glicko/Poisson не моделируют:

- травмы ключевых игроков;
- последние матчи (форма, темп);
- позиция в турнирной таблице;
- сезонные «профитные» паттерны команды.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class AccuracyAdjustments:
    home_rating_delta: float = 0.0
    away_rating_delta: float = 0.0
    home_xg_factor: float = 1.0
    away_xg_factor: float = 1.0
    notes: list[str] = None  # type: ignore[assignment]

    def __post_init__(self) -> None:
        if self.notes is None:
            self.notes = []


# ── Травмы ─────────────────────────────────────────────────────────────
def _injury_severity(reason: str | None) -> float:
    """0..1 — насколько игрок «дорогой». Heuristic на ключевых словах."""
    if not reason:
        return 0.4
    low = reason.lower()
    if any(k in low for k in ("acl", "operation", "long-term", "season-ending")):
        return 1.0
    if any(k in low for k in ("hamstring", "knee", "thigh", "fracture", "muscle")):
        return 0.8
    if any(k in low for k in ("doubtful", "fitness", "tired")):
        return 0.4
    if any(k in low for k in ("suspended", "ban", "red card")):
        return 0.6
    return 0.5


def adjust_for_injuries(
    home_team_id: int | None,
    away_team_id: int | None,
    injuries: list[dict[str, Any]] | None,
    *,
    base_penalty: float = 8.0,  # очков Glicko за «средне-важного» игрока
) -> AccuracyAdjustments:
    adj = AccuracyAdjustments()
    if not injuries:
        return adj
    home_loss = away_loss = 0.0
    home_count = away_count = 0
    for entry in injuries:
        if not isinstance(entry, dict):
            continue
        team = entry.get("team") or {}
        team_id = team.get("id") if isinstance(team, dict) else None
        sev = _injury_severity(entry.get("reason") or entry.get("status"))
        # Предположение: «role»/«importance» если есть — учитываем
        importance_field = entry.get("importance") or entry.get("role") or 1.0
        try:
            importance = float(importance_field)
        except (TypeError, ValueError):
            importance = 1.0
        loss = base_penalty * sev * max(0.5, min(2.0, importance))
        if team_id == home_team_id:
            home_loss += loss
            home_count += 1
        elif team_id == away_team_id:
            away_loss += loss
            away_count += 1
    adj.home_rating_delta -= home_loss
    adj.away_rating_delta -= away_loss
    if home_count:
        adj.notes.append(f"🚑 Травмы хозяев: {home_count} (−{home_loss:.0f} GL)")
    if away_count:
        adj.notes.append(f"🚑 Травмы гостей: {away_count} (−{away_loss:.0f} GL)")
    return adj


# ── Форма последних матчей ─────────────────────────────────────────────
def adjust_for_last_games(
    last_games: dict[str, Any] | None,
) -> AccuracyAdjustments:
    """Если в последних матчах команда забивала больше xG — подтянем xG."""
    adj = AccuracyAdjustments()
    if not last_games or not isinstance(last_games, dict):
        return adj
    home_recent = last_games.get("home") or last_games.get("homeTeam") or {}
    away_recent = last_games.get("away") or last_games.get("awayTeam") or {}
    if isinstance(home_recent, dict):
        avg_xg_for = _safe_float(home_recent.get("avgXgFor"))
        avg_xg_against = _safe_float(home_recent.get("avgXgAgainst"))
        if avg_xg_for and avg_xg_for > 1.0:
            factor = min(1.0 + (avg_xg_for - 1.5) * 0.05, 1.15)
            adj.home_xg_factor *= factor
        if avg_xg_against and avg_xg_against < 1.2:
            adj.away_xg_factor *= 0.95
    if isinstance(away_recent, dict):
        avg_xg_for = _safe_float(away_recent.get("avgXgFor"))
        avg_xg_against = _safe_float(away_recent.get("avgXgAgainst"))
        if avg_xg_for and avg_xg_for > 1.0:
            factor = min(1.0 + (avg_xg_for - 1.5) * 0.05, 1.15)
            adj.away_xg_factor *= factor
        if avg_xg_against and avg_xg_against < 1.2:
            adj.home_xg_factor *= 0.95
    if adj.home_xg_factor != 1.0 or adj.away_xg_factor != 1.0:
        adj.notes.append(
            f"📊 Поправка xG по форме: home×{adj.home_xg_factor:.2f}, "
            f"away×{adj.away_xg_factor:.2f}"
        )
    return adj


# ── Турнирная таблица ──────────────────────────────────────────────────
def adjust_for_standings(
    home_team_id: int | None,
    away_team_id: int | None,
    season_table: dict[str, Any] | None,
) -> AccuracyAdjustments:
    """Команды в топе таблицы получают небольшой буст рейтинга, аутсайдеры — штраф."""
    adj = AccuracyAdjustments()
    if not season_table or not isinstance(season_table, dict):
        return adj
    rows = season_table.get("standings") or season_table.get("rows") or []
    if not isinstance(rows, list) or not rows:
        return adj
    n = len(rows)
    home_pos = None
    away_pos = None
    for i, row in enumerate(rows, start=1):
        if not isinstance(row, dict):
            continue
        team = row.get("team") or {}
        tid = team.get("id") if isinstance(team, dict) else None
        if tid == home_team_id:
            home_pos = i
        if tid == away_team_id:
            away_pos = i
    if home_pos is not None:
        delta = (n / 2 - home_pos) / n * 30.0
        adj.home_rating_delta += delta
        adj.notes.append(f"🏆 Хозяева в таблице: {home_pos}/{n} ({delta:+.0f} GL)")
    if away_pos is not None:
        delta = (n / 2 - away_pos) / n * 30.0
        adj.away_rating_delta += delta
        adj.notes.append(f"🏆 Гости в таблице: {away_pos}/{n} ({delta:+.0f} GL)")
    return adj


# ── Профитность / маржинальные паттерны ────────────────────────────────
def adjust_for_profits(
    profits: dict[str, Any] | None,
) -> AccuracyAdjustments:
    """Анализ исторических профитных паттернов команды.

    Если команда исторически прибыльна на ТБ/ТМ, подкорректируем xG.
    """
    adj = AccuracyAdjustments()
    if not profits or not isinstance(profits, dict):
        return adj
    # Извлекаем ROI по тоталам
    over_roi = _safe_float(profits.get("overRoi") or profits.get("over_roi"))
    under_roi = _safe_float(profits.get("underRoi") or profits.get("under_roi"))
    if over_roi is not None and over_roi > 10.0:
        boost = min(1.0 + over_roi / 500.0, 1.08)
        adj.home_xg_factor *= boost
        adj.away_xg_factor *= boost
        adj.notes.append(f"📈 Профит тоталов ТБ: ROI {over_roi:.0f}% (+xG ×{boost:.2f})")
    elif under_roi is not None and under_roi > 10.0:
        shrink = max(1.0 - under_roi / 500.0, 0.92)
        adj.home_xg_factor *= shrink
        adj.away_xg_factor *= shrink
        adj.notes.append(f"📉 Профит тоталов ТМ: ROI {under_roi:.0f}% (−xG ×{shrink:.2f})")
    return adj


# ── Домашнее преимущество (доп. фактор) ───────────────────────────────
def adjust_for_home_advantage(
    last_games: dict[str, Any] | None,
) -> AccuracyAdjustments:
    """Дополнительный буст за домашнюю серию побед."""
    adj = AccuracyAdjustments()
    if not last_games or not isinstance(last_games, dict):
        return adj
    home_recent = last_games.get("home") or last_games.get("homeTeam") or {}
    if not isinstance(home_recent, dict):
        return adj
    # Серия побед дома
    wins = _safe_float(home_recent.get("homeWins") or home_recent.get("wins"))
    total = _safe_float(home_recent.get("homeGames") or home_recent.get("total"))
    if wins is not None and total is not None and total >= 3:
        win_rate = wins / max(total, 1)
        if win_rate >= 0.7:
            delta = min((win_rate - 0.5) * 40.0, 20.0)
            adj.home_rating_delta += delta
            adj.notes.append(
                f"🏟 Домашнее преимущество: {wins:.0f}/{total:.0f} побед "
                f"({delta:+.0f} GL)"
            )
    return adj


def merge_adjustments(
    *adjustments: AccuracyAdjustments,
) -> AccuracyAdjustments:
    out = AccuracyAdjustments()
    for adj in adjustments:
        out.home_rating_delta += adj.home_rating_delta
        out.away_rating_delta += adj.away_rating_delta
        out.home_xg_factor *= adj.home_xg_factor
        out.away_xg_factor *= adj.away_xg_factor
        out.notes.extend(adj.notes)
    return out


def _safe_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(str(value))
    except (TypeError, ValueError):
        return None


__all__ = [
    "AccuracyAdjustments",
    "adjust_for_home_advantage",
    "adjust_for_injuries",
    "adjust_for_last_games",
    "adjust_for_profits",
    "adjust_for_standings",
    "merge_adjustments",
]
