"""Тесты HealthService."""

from __future__ import annotations

import pytest

from services.health_check import HealthService, HealthStatus


@pytest.mark.asyncio
async def test_empty_service_report_unknown():
    s = HealthService()
    r = await s.run_all()
    assert r.overall == HealthStatus.UNKNOWN
    assert r.components == []


@pytest.mark.asyncio
async def test_all_up():
    s = HealthService()

    async def up_check():
        return HealthStatus.UP, "good"

    s.register("a", up_check)
    s.register("b", up_check)
    r = await s.run_all()
    assert r.overall == HealthStatus.UP
    assert len(r.components) == 2


@pytest.mark.asyncio
async def test_one_degraded():
    s = HealthService()

    async def up():
        return HealthStatus.UP, ""

    async def deg():
        return HealthStatus.DEGRADED, "slow"

    s.register("a", up)
    s.register("b", deg)
    r = await s.run_all()
    assert r.overall == HealthStatus.DEGRADED


@pytest.mark.asyncio
async def test_one_down():
    s = HealthService()

    async def up():
        return HealthStatus.UP, ""

    async def down():
        return HealthStatus.DOWN, "offline"

    s.register("a", up)
    s.register("b", down)
    r = await s.run_all()
    assert r.overall == HealthStatus.DOWN


@pytest.mark.asyncio
async def test_exception_counts_as_down():
    s = HealthService()

    async def bad():
        raise RuntimeError("boom")

    s.register("broken", bad)
    r = await s.run_all()
    assert r.overall == HealthStatus.DOWN
    assert r.components[0].status == HealthStatus.DOWN
    assert "RuntimeError" in r.components[0].detail


@pytest.mark.asyncio
async def test_unregister():
    s = HealthService()

    async def up():
        return HealthStatus.UP, ""

    s.register("x", up)
    s.unregister("x")
    r = await s.run_all()
    assert len(r.components) == 0


@pytest.mark.asyncio
async def test_latency_measured():
    s = HealthService()

    async def up():
        return HealthStatus.UP, ""

    s.register("a", up)
    r = await s.run_all()
    assert r.components[0].latency_ms >= 0
