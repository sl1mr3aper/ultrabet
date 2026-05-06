"""Публикация событий в внешние webhook-эндпоинты.

Используется:
- отправка подписанным каналам о новых EV ставках (public feed).
- отправка в админ-канал: ошибки, статистика.
- интеграция с внешними аналитиками (e.g. Grafana, Datadog).
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

import aiohttp
from loguru import logger


@dataclass(slots=True)
class WebhookTarget:
    url: str
    secret: str | None = None
    event_types: tuple[str, ...] | None = None  # None = все
    retries: int = 3
    timeout_seconds: float = 5.0


class WebhookPublisher:
    def __init__(self) -> None:
        self._targets: list[WebhookTarget] = []
        self._session: aiohttp.ClientSession | None = None
        self._sent = 0
        self._failed = 0

    def add_target(self, target: WebhookTarget) -> None:
        self._targets.append(target)

    def remove_target(self, url: str) -> None:
        self._targets = [t for t in self._targets if t.url != url]

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None

    async def publish(self, event_type: str, payload: dict[str, Any]) -> int:
        """Отправить событие всем подписчикам, вернуть число успешных."""
        delivered = 0
        session = await self._get_session()
        body = json.dumps({"type": event_type, "data": payload})
        for target in self._targets:
            if target.event_types and event_type not in target.event_types:
                continue
            ok = await self._send_one(session, target, body)
            if ok:
                delivered += 1
                self._sent += 1
            else:
                self._failed += 1
        return delivered

    async def _send_one(
        self,
        session: aiohttp.ClientSession,
        target: WebhookTarget,
        body: str,
    ) -> bool:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if target.secret:
            headers["X-Webhook-Secret"] = target.secret
        for attempt in range(1, target.retries + 1):
            try:
                async with session.post(
                    target.url,
                    data=body,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=target.timeout_seconds),
                ) as resp:
                    if 200 <= resp.status < 300:
                        return True
                    logger.warning(
                        "webhook {} вернул статус {} (попытка {})",
                        target.url, resp.status, attempt,
                    )
            except Exception as exc:
                logger.warning(
                    "webhook {} ошибка (попытка {}): {}",
                    target.url, attempt, exc,
                )
            await asyncio.sleep(0.25 * attempt)
        return False

    @property
    def stats(self) -> dict[str, int]:
        return {"sent": self._sent, "failed": self._failed, "targets": len(self._targets)}


__all__ = ["WebhookPublisher", "WebhookTarget"]
