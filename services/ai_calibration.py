"""AI-калибровочный советник — Gemini анализирует метрики модели.

После каждого snapshot (SelfLearner / CalibrationService) вызывается
`ai_calibration_check()`, который:
1. Формирует промпт с текущими Brier, log-loss, калибровочными
   корзинами, hit-rate по рынкам.
2. Отправляет в Gemini и парсит рекомендации.
3. Логирует результат и опционально корректирует параметры модели
   (Dixon-Coles rho, ensemble weights, home advantage).

Это НЕ замена калибровки — это дополнительный «второй глаз»,
который работает асинхронно и пишет рекомендации в лог.
"""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp
from loguru import logger

from services.self_learner import LearningSnapshot

_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


async def ai_calibration_check(
    snapshot: LearningSnapshot,
    api_key: str,
    *,
    model: str = "gemini-2.5-flash-lite",
    timeout: float = 20.0,
) -> dict[str, Any] | None:
    """Запрашивает у Gemini анализ калибровочного snapshot.

    Возвращает dict с рекомендациями или None при ошибке.
    """
    if not api_key or snapshot.samples < 10:
        return None

    # Калибровочные корзины
    bins_text = "\n".join(
        f"  [{b.lower:.2f}-{b.upper:.2f}]: "
        f"count={b.count}, hits={b.hits}, "
        f"empirical={b.empirical:.3f}, midpoint={b.midpoint:.3f}"
        for b in snapshot.calibration
    )

    # Hit-rate по рынкам
    market_lines = []
    for key, (total_count, hit_count) in sorted(
        snapshot.market_hit_rates.items(),
        key=lambda x: x[1][0],
        reverse=True,
    )[:10]:
        rate = hit_count / max(total_count, 1) * 100
        market_lines.append(f"  {key}: {hit_count}/{total_count} ({rate:.1f}%)")
    markets_text = "\n".join(market_lines) if market_lines else "  нет данных"

    prompt = (
        "Ты — ML-инженер по калибровке спортивных моделей.\n"
        "Проанализируй метрики модели и дай конкретные рекомендации.\n\n"
        f"МЕТРИКИ:\n"
        f"  Brier score: {snapshot.brier:.4f}\n"
        f"  Log-loss: {snapshot.log_loss:.4f}\n"
        f"  Семплов: {snapshot.samples}\n\n"
        f"КАЛИБРОВОЧНЫЕ КОРЗИНЫ (predicted prob → actual hit-rate):\n"
        f"{bins_text}\n\n"
        f"HIT-RATE ПО РЫНКАМ:\n"
        f"{markets_text}\n\n"
        "ТЕКУЩАЯ МОДЕЛЬ: Glicko-2 + Dixon-Coles Poisson, ансамбль 55/45,\n"
        "Dixon-Coles rho=-0.13, per-league home advantage.\n\n"
        "ФОРМАТ ОТВЕТА (строго JSON, без markdown):\n"
        '{"analysis": "2-3 предложения: что хорошо/плохо в калибровке",\n'
        ' "rho_suggestion": число от -0.20 до 0.0 (текущее -0.13),\n'
        ' "glicko_weight_suggestion": число от 0.40 до 0.70 (текущее 0.55),\n'
        ' "priority_markets": ["рынки которые модель предсказывает лучше всего"],\n'
        ' "weak_markets": ["рынки где модель слабее всего"]}\n'
    )

    try:
        result = await asyncio.wait_for(
            _call_gemini(prompt, api_key, model), timeout=timeout,
        )
    except TimeoutError:
        logger.debug("AI calibration: timeout")
        return None
    except Exception as exc:
        logger.debug("AI calibration error: {}", exc)
        return None

    if not result:
        return None

    # Пробуем распарсить JSON из ответа
    import json
    text = result.strip()
    # Убираем markdown-обёртку если есть
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(
            l for l in lines if not l.startswith("```")
        )

    try:
        recommendations = json.loads(text)
    except json.JSONDecodeError:
        logger.info("AI calibration raw response: {}", text[:500])
        return {"raw": text}

    # Применяем рекомендации автоматически если они в разумных пределах
    _apply_recommendations(recommendations)

    logger.info(
        "AI calibration: analysis='{}', rho={}, glicko_w={}",
        recommendations.get("analysis", "")[:100],
        recommendations.get("rho_suggestion"),
        recommendations.get("glicko_weight_suggestion"),
    )
    return recommendations


def _apply_recommendations(rec: dict[str, Any]) -> None:
    """Осторожно применяем AI-рекомендации к параметрам модели."""
    # Dixon-Coles rho
    rho = rec.get("rho_suggestion")
    if isinstance(rho, (int, float)) and -0.25 <= rho <= 0.0:
        import core.poisson_model as pm
        pm.DC_RHO_DEFAULT = float(rho)
        logger.info("AI calibration: updated DC_RHO_DEFAULT to {:.3f}", rho)

    # Ensemble weights
    gw = rec.get("glicko_weight_suggestion")
    if isinstance(gw, (int, float)) and 0.35 <= gw <= 0.75:
        from core.ensemble import update_adaptive_weights
        # Конвертируем вес в псевдо-brier для update_adaptive_weights:
        # если gw=0.6 → glicko brier должен быть ниже
        pw = 1.0 - float(gw)
        update_adaptive_weights(
            glicko_brier=pw,
            poisson_brier=float(gw),
        )
        logger.info(
            "AI calibration: updated ensemble weights, glicko_target={:.2f}", gw,
        )


async def _call_gemini(prompt: str, api_key: str, model: str) -> str | None:
    url = f"{_API_BASE}/{model}:generateContent?key={api_key}"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.15,
            "maxOutputTokens": 500,
            "topP": 0.80,
        },
    }
    timeout_cfg = aiohttp.ClientTimeout(total=20.0)
    async with aiohttp.ClientSession(timeout=timeout_cfg) as session, session.post(
        url, json=body, headers={"Content-Type": "application/json"},
    ) as resp:
        if resp.status != 200:
            return None
        try:
            payload = await resp.json()
        except (ValueError, aiohttp.ContentTypeError):
            return None
    candidates = payload.get("candidates") or []
    if not candidates:
        return None
    content = candidates[0].get("content") or {}
    parts = content.get("parts") or []
    if not parts:
        return None
    return "".join(
        p.get("text", "") for p in parts if isinstance(p, dict)
    ).strip() or None


__all__ = ["ai_calibration_check"]
