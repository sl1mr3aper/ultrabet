r"""Уточнение топ-1 главного прогноза через Gemini (Google Generative AI).

Принимает на вход агрегат данных матча (составы, форма, травмы, кфы,
вероятности модели) и возвращает короткий human-readable текст:
  • что повышает уверенность в главном прогнозе;
  • что может его сломать;
  • альтернативный прогноз, если основной риск-overweight.

API: REST endpoint generativelanguage.googleapis.com, free-tier ключ
из config.gemini_api_key. Для устойчивости — graceful timeout
и кэш на game_id × prediction-snapshot 30 минут.

Возвращаемый текст приходит как plain-text — символы, особенные для
Markdown в Telegram, очищаются на стороне формирующего отчёт кода.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

import aiohttp
from loguru import logger

from services.prediction_service import PredictionResult

_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


@dataclass
class _CacheEntry:
    text: str
    expires_at: float


@dataclass
class GeminiRefiner:
    api_key: str
    model: str = "gemini-2.5-flash-lite"
    timeout: float = 15.0
    cache_ttl: float = 1800.0
    _cache: dict[int, _CacheEntry] = field(default_factory=dict)

    async def refine(self, result: PredictionResult, raw: dict[str, Any] | None = None) -> str | None:
        """Вернуть короткое текстовое уточнение. None — если AI отключён или упал."""
        if not self.api_key:
            return None
        cached = self._cache.get(result.game_id)
        now = time.monotonic()
        if cached and cached.expires_at > now:
            return cached.text

        prompt = self._build_prompt(result, raw)
        try:
            text = await asyncio.wait_for(
                self._call_gemini(prompt), timeout=self.timeout,
            )
        except TimeoutError:
            logger.debug("Gemini timeout for game={}", result.game_id)
            return None
        except Exception as exc:
            logger.debug("Gemini error: {}", exc)
            return None

        if text is None:
            return None
        text = text.strip()
        if not text:
            return None
        self._cache[result.game_id] = _CacheEntry(
            text=text, expires_at=now + self.cache_ttl,
        )
        return text

    def _build_prompt(
        self,
        result: PredictionResult,
        raw: dict[str, Any] | None,
    ) -> str:
        # Локальный импорт — чтобы не плодить циклы при тестах сервиса.
        from bot.formatters import _pick_top_one
        from core.markets import label_for

        pick_tuple = _pick_top_one(result)
        if pick_tuple is None:
            top_pick_block = "Главный прогноз: модель не определила."
        else:
            pick_key, pick_prob, _pick_odd, _pick_book = pick_tuple
            try:
                pick_label = label_for(
                    pick_key, home=result.home_name, away=result.away_name,
                )
            except Exception:
                pick_label = pick_key
            top_pick_block = (
                "ГЛАВНЫЙ ПИК (ровно его обсуждай, не предлагай свой):\n"
                f"  • Рынок: {pick_label} (key={pick_key})\n"
                f"  • Вероятность модели: {pick_prob * 100:.1f}%"
            )

        # Топ-8 рынков с вероятностями (БЕЗ коэффициентов — запрещено)
        top_markets = sorted(
            result.probabilities.items(), key=lambda kv: kv[1], reverse=True,
        )[:8]
        prob_lines = []
        for key, prob in top_markets:
            try:
                lab = label_for(key, home=result.home_name, away=result.away_name)
            except Exception:
                lab = key
            prob_lines.append(f"  - {lab}: prob={prob * 100:.1f}%")

        injuries = ""
        if isinstance(raw, dict):
            inj = raw.get("injuries") or []
            if isinstance(inj, list) and inj:
                injuries = "Injuries: " + "; ".join(
                    f"{(p.get('player') or {}).get('name', '?')}({p.get('status', '?')})"
                    for p in inj[:6]
                    if isinstance(p, dict)
                )

        last_games = ""
        if isinstance(raw, dict):
            lg = raw.get("last_games") or {}
            if isinstance(lg, dict):
                home_form = lg.get("homeForm") or lg.get("home_form") or ""
                away_form = lg.get("awayForm") or lg.get("away_form") or ""
                if home_form or away_form:
                    last_games = f"Form: home={home_form}, away={away_form}"

        return (
            "Ты футбольный аналитик. Тебе дан конкретный ГЛАВНЫЙ ПРОГНОЗ — "
            "обсуждай только его, не выдумывай свой, не путай с другими "
            "рынками из списка вероятностей.\n"
            "ЖЁСТКИЕ ПРАВИЛА ответа:\n"
            "• Язык: русский. Тон: деловой, без воды, без «возможно», "
            "«стоит отметить», «на мой взгляд», без комплиментов модели.\n"
            "• РОВНО 3 строки. Каждая ≤ 110 символов. Без Markdown, "
            "без звёздочек, без списков, без заголовков.\n"
            "• Никаких коэффициентов, кфов, odds, маржи, fair-value.\n"
            "• Опираться строго на факты ниже: xG, Glicko, форма, травмы. "
            "Если данных нет — не упоминать.\n"
            "• ЗАПРЕЩЕНО писать пустые слова без обоснования: «подтверждаю», "
            "«согласен с моделью», «всё ок». Любая оценка должна содержать "
            "конкретное число или факт ИЗ ОТЧЁТА (xG, Glicko, разница в "
            "форме, ключевая травма).\n"
            "Расшифровка сокращений: ИТМ/ИТБ — инд. тотал меньше/больше, "
            "ТМ/ТБ — общий тотал, ОЗ — обе забьют, Двойной шанс — 1X/X2/12, "
            "Фора — гандикап.\n"
            "Формат (ровно 3 строки, строго в этом порядке):\n"
            "1) ✅ Надёжность: 1 конкретный факт из отчёта, который "
            "поддерживает ГЛАВНЫЙ ПРОГНОЗ (например xG 1.54 vs 1.06 — "
            "поддерживает ТМ; Glicko +50 у хозяев — поддерживает П1).\n"
            "2) 🎯 Вердикт: «брать», «не брать» или «осторожно» — "
            "решение по ГЛАВНОМУ ПРОГНОЗУ, обязательно с цифрой/фактом из "
            "отчёта (xG, Glicko, форма, травма ключевого игрока). НЕ "
            "использовать слово «подтверждаю».\n"
            "3) 💬 Стиль игры: краткий вывод о силе и стиле обеих команд "
            "и ожидаемом сценарии (атакующий темп / закрытая игра / "
            "ставка на одну атаку), без привязки к котировке.\n\n"
            f"Матч: {result.home_name} vs {result.away_name}\n"
            f"Лига: {result.league_name or '?'} ({result.country_raw or '?'})\n"
            f"Дата: {result.date_iso or '?'}\n"
            f"xG модель: {result.home_name}={result.home_xg:.2f}, "
            f"{result.away_name}={result.away_xg:.2f}\n"
            f"Glicko: {result.home_name}={result.home_rating:.0f}, "
            f"{result.away_name}={result.away_rating:.0f}\n\n"
            f"{top_pick_block}\n\n"
            "Топ-вероятности модели (для контекста, но обсуждай только "
            "ГЛАВНЫЙ ПРОГНОЗ выше):\n" + "\n".join(prob_lines)
            + ("\n" + injuries if injuries else "")
            + ("\n" + last_games if last_games else "")
        )

    async def refine_text(self, prompt: str) -> str | None:
        """Универсальная обёртка: получить короткий ответ Gemini по промпту.

        Используется не только в карточке прогноза, но и в турнирной таблице
        (короткое резюме лидеров и середняков). Без таймаута Gemini может
        висеть, поэтому защищаемся `wait_for(timeout)`.
        """
        if not self.api_key:
            return None
        prompt = (prompt or "").strip()
        if not prompt:
            return None
        try:
            text = await asyncio.wait_for(
                self._call_gemini(prompt), timeout=self.timeout,
            )
        except TimeoutError:
            logger.debug("Gemini timeout (refine_text)")
            return None
        except Exception as exc:
            logger.debug("Gemini error (refine_text): {}", exc)
            return None
        if not text:
            return None
        return text.strip() or None

    async def _call_gemini(self, prompt: str) -> str | None:
        url = f"{_API_BASE}/{self.model}:generateContent?key={self.api_key}"
        body = {
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": 0.25,
                "maxOutputTokens": 320,
                "topP": 0.85,
            },
        }
        timeout_cfg = aiohttp.ClientTimeout(total=self.timeout)
        async with aiohttp.ClientSession(timeout=timeout_cfg) as session, session.post(
            url,
            json=body,
            headers={"Content-Type": "application/json"},
        ) as resp:
            if resp.status != 200:
                body_text = (await resp.text())[:200]
                logger.debug("Gemini HTTP {}: {}", resp.status, body_text)
                return None
            try:
                payload = await resp.json()
            except (ValueError, aiohttp.ContentTypeError):
                return None
        candidates = payload.get("candidates") or []
        if not candidates:
            return None
        first = candidates[0]
        content = first.get("content") or {}
        parts = content.get("parts") or []
        if not parts:
            return None
        text_chunks = [p.get("text", "") for p in parts if isinstance(p, dict)]
        return "".join(text_chunks).strip() or None


__all__ = ["GeminiRefiner"]
