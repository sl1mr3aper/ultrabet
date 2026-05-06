"""Oracle: главный регулятор вероятностей.

Принимает baseline-вероятности (после ансамбля + калибровки), bundle с
сырыми данными и (опционально) odds_map. Применяет все факторы из
``factors.py`` с весами из ``weights.py``, агрегирует сдвиги, клампит
суммарный сдвиг по рынку и нормализует группы (1×2, тоталы pair-wise).

Контракт:
- Чистый pure-функциональный класс. Не делает сетевых запросов.
- Возвращает новый dict вероятностей (исходный не мутирует).
- Если данных не хватает — возвращает входные вероятности почти не
  изменёнными (защитные фолбэки в каждом факторе).
"""

from __future__ import annotations

from typing import Any

from loguru import logger

from services.oracle.factors import (
    FactorResult,
    factor_form,
    factor_h2h_profits,
    factor_injuries,
    factor_market_drift,
    factor_motivation,
)
from services.oracle.weights import (
    DEFAULT_WEIGHTS,
    MAX_TOTAL_DELTA,
)


class Oracle:
    def __init__(self, weights: dict[str, float] | None = None) -> None:
        self._weights = weights or DEFAULT_WEIGHTS

    def refine(
        self,
        probabilities: dict[str, float],
        *,
        bundle: dict[str, Any] | None = None,
        odds_map: dict[str, float] | None = None,
    ) -> dict[str, float]:
        """Возвращает новый dict с уточнёнными вероятностями.

        Aggressive defensive: при любых ошибках возвращает входной dict
        без изменений (логируем DEBUG).
        """
        if not probabilities:
            return probabilities
        bundle = bundle or {}
        odds_map = odds_map or {}

        try:
            home_id, away_id = self._extract_team_ids(bundle)
        except Exception:
            home_id, away_id = None, None

        try:
            results = self._run_factors(
                bundle=bundle,
                probabilities=probabilities,
                odds_map=odds_map,
                home_id=home_id,
                away_id=away_id,
            )
        except Exception as exc:
            logger.debug("Oracle.refine: factors failed: {}", exc)
            return probabilities

        try:
            shifts = self._aggregate(results)
        except Exception as exc:
            logger.debug("Oracle.refine: aggregate failed: {}", exc)
            return probabilities

        try:
            return self._apply_and_normalize(probabilities, shifts)
        except Exception as exc:
            logger.debug("Oracle.refine: apply failed: {}", exc)
            return probabilities

    # ── helpers ────────────────────────────────────────────────

    def _extract_team_ids(
        self, bundle: dict[str, Any]
    ) -> tuple[int | None, int | None]:
        game = bundle.get("game")
        if not isinstance(game, dict):
            return None, None
        home = game.get("homeTeam") or {}
        away = game.get("awayTeam") or {}
        home_id = home.get("id") if isinstance(home, dict) else None
        away_id = away.get("id") if isinstance(away, dict) else None
        try:
            home_id_int = int(home_id) if home_id is not None else None
        except (TypeError, ValueError):
            home_id_int = None
        try:
            away_id_int = int(away_id) if away_id is not None else None
        except (TypeError, ValueError):
            away_id_int = None
        return home_id_int, away_id_int

    def _run_factors(
        self,
        *,
        bundle: dict[str, Any],
        probabilities: dict[str, float],
        odds_map: dict[str, float],
        home_id: int | None,
        away_id: int | None,
    ) -> list[FactorResult]:
        results: list[FactorResult] = []
        try:
            results.append(
                factor_injuries(bundle, home_id=home_id, away_id=away_id)
            )
        except Exception as exc:
            logger.debug("factor_injuries error: {}", exc)
        try:
            results.append(factor_form(bundle))
        except Exception as exc:
            logger.debug("factor_form error: {}", exc)
        try:
            results.append(
                factor_motivation(bundle, home_id=home_id, away_id=away_id)
            )
        except Exception as exc:
            logger.debug("factor_motivation error: {}", exc)
        try:
            results.append(
                factor_h2h_profits(bundle, home_id=home_id, away_id=away_id)
            )
        except Exception as exc:
            logger.debug("factor_h2h_profits error: {}", exc)
        try:
            results.append(
                factor_market_drift(
                    probabilities=probabilities, odds_map=odds_map
                )
            )
        except Exception as exc:
            logger.debug("factor_market_drift error: {}", exc)
        return results

    def _aggregate(
        self, results: list[FactorResult]
    ) -> dict[str, float]:
        total: dict[str, float] = {}
        for r in results:
            if r.confidence <= 0 or not r.shifts:
                continue
            weight = self._weights.get(r.name, 1.0) * r.confidence
            for key, delta in r.shifts.items():
                total[key] = total.get(key, 0.0) + delta * weight
        # Глобальный клампинг по рынку
        return {
            k: max(-MAX_TOTAL_DELTA, min(MAX_TOTAL_DELTA, v))
            for k, v in total.items()
        }

    def _apply_and_normalize(
        self,
        probabilities: dict[str, float],
        shifts: dict[str, float],
    ) -> dict[str, float]:
        out: dict[str, float] = {}
        for key, prob in probabilities.items():
            new_p = prob + shifts.get(key, 0.0)
            new_p = max(0.005, min(0.995, new_p))
            out[key] = new_p

        # Нормализация 1×2 (сумма = 1)
        out = self._renorm_group(out, ["1", "X", "2"])
        # Нормализация двойного шанса (1X+X2+12 = 2 — это «производные»,
        # их пересчитываем из 1×2 после нормализации, чтобы остаться
        # консистентными)
        if all(k in out for k in ("1", "X", "2")):
            out["1X"] = out["1"] + out["X"]
            out["X2"] = out["X"] + out["2"]
            out["12"] = out["1"] + out["2"]
            out["DNB_HOME"] = out["1"] / max(1e-6, out["1"] + out["2"])
            out["DNB_AWAY"] = out["2"] / max(1e-6, out["1"] + out["2"])
        # BTTS: пара BTTS + BTTS_NO = 1
        out = self._renorm_pair(out, "BTTS", "BTTS_NO")
        # Тоталы: пары over+under = 1
        for low in ("05", "15", "25", "35", "45", "55"):
            out = self._renorm_pair(out, f"O{low}", f"U{low}")
            out = self._renorm_pair(out, f"HT_O{low}", f"HT_U{low}")
            out = self._renorm_pair(out, f"AT_O{low}", f"AT_U{low}")
        return out

    def _renorm_group(
        self, probs: dict[str, float], keys: list[str]
    ) -> dict[str, float]:
        present = [k for k in keys if k in probs]
        if len(present) < 2:
            return probs
        s = sum(probs[k] for k in present)
        if s <= 0:
            return probs
        out = dict(probs)
        for k in present:
            out[k] = probs[k] / s
        return out

    def _renorm_pair(
        self, probs: dict[str, float], a: str, b: str
    ) -> dict[str, float]:
        if a not in probs or b not in probs:
            return probs
        s = probs[a] + probs[b]
        if s <= 0:
            return probs
        out = dict(probs)
        out[a] = probs[a] / s
        out[b] = probs[b] / s
        return out


__all__ = ["Oracle"]
