"""Health checks для админ-дашборда: SStats API, DB, кэш, планировщик.

Используется:
- /admin_health — быстрый обзор состояния всех компонентов.
- ops-метрики (uptime, last_error, latency).
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class HealthStatus(str, Enum):
    UP = "up"
    DEGRADED = "degraded"
    DOWN = "down"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class ComponentHealth:
    name: str
    status: HealthStatus
    latency_ms: float
    checked_at: datetime
    detail: str = ""


@dataclass(slots=True)
class HealthReport:
    overall: HealthStatus
    components: list[ComponentHealth] = field(default_factory=list)
    timestamp: datetime = field(default_factory=datetime.utcnow)


HealthCheck = Callable[[], Awaitable[tuple[HealthStatus, str]]]


class HealthService:
    def __init__(self) -> None:
        self._checks: dict[str, HealthCheck] = {}

    def register(self, name: str, check: HealthCheck) -> None:
        self._checks[name] = check

    def unregister(self, name: str) -> None:
        self._checks.pop(name, None)

    async def run_all(self) -> HealthReport:
        components: list[ComponentHealth] = []
        for name, check in self._checks.items():
            start = time.monotonic()
            status = HealthStatus.UNKNOWN
            detail = ""
            try:
                status, detail = await check()
            except Exception as exc:
                status = HealthStatus.DOWN
                detail = f"{type(exc).__name__}: {exc}"
            latency = (time.monotonic() - start) * 1000.0
            components.append(
                ComponentHealth(
                    name=name,
                    status=status,
                    latency_ms=latency,
                    checked_at=datetime.utcnow(),
                    detail=detail,
                )
            )
        overall = self._compute_overall(components)
        return HealthReport(overall=overall, components=components)

    @staticmethod
    def _compute_overall(components: list[ComponentHealth]) -> HealthStatus:
        if not components:
            return HealthStatus.UNKNOWN
        statuses = {c.status for c in components}
        if HealthStatus.DOWN in statuses:
            return HealthStatus.DOWN
        if HealthStatus.DEGRADED in statuses:
            return HealthStatus.DEGRADED
        if HealthStatus.UNKNOWN in statuses:
            return HealthStatus.DEGRADED
        return HealthStatus.UP


async def check_sstats(client) -> tuple[HealthStatus, str]:
    """Типовой health-check для SStats."""
    try:
        info = await asyncio.wait_for(client.get_account_info(), timeout=3.0)
        if info is None:
            return HealthStatus.DEGRADED, "empty account info"
        return HealthStatus.UP, "OK"
    except TimeoutError:
        return HealthStatus.DEGRADED, "timeout"
    except Exception as exc:
        return HealthStatus.DOWN, f"{type(exc).__name__}: {exc}"


__all__ = [
    "ComponentHealth",
    "HealthCheck",
    "HealthReport",
    "HealthService",
    "HealthStatus",
    "check_sstats",
]
