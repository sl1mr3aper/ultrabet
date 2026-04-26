"""Тесты InMemoryCache."""

from __future__ import annotations

import asyncio

import pytest

from services.cache_store import InMemoryCache


@pytest.mark.asyncio
async def test_set_and_get():
    c = InMemoryCache()
    await c.set("a", 42)
    assert await c.get("a") == 42


@pytest.mark.asyncio
async def test_get_missing_returns_none():
    c = InMemoryCache()
    assert await c.get("x") is None


@pytest.mark.asyncio
async def test_expires():
    c = InMemoryCache(default_ttl=0.05)
    await c.set("a", 1)
    await asyncio.sleep(0.1)
    assert await c.get("a") is None


@pytest.mark.asyncio
async def test_custom_ttl():
    c = InMemoryCache(default_ttl=0.01)
    await c.set("a", 1, ttl=1.0)
    await asyncio.sleep(0.05)
    assert await c.get("a") == 1


@pytest.mark.asyncio
async def test_delete():
    c = InMemoryCache()
    await c.set("a", 1)
    assert await c.delete("a") is True
    assert await c.delete("a") is False


@pytest.mark.asyncio
async def test_tag_invalidation():
    c = InMemoryCache()
    await c.set("a", 1, tags=["users"])
    await c.set("b", 2, tags=["users", "extras"])
    await c.set("c", 3, tags=["extras"])
    count = await c.invalidate_tag("users")
    assert count == 2
    assert await c.get("a") is None
    assert await c.get("b") is None
    assert await c.get("c") == 3


@pytest.mark.asyncio
async def test_clear():
    c = InMemoryCache()
    for i in range(10):
        await c.set(f"k{i}", i)
    assert await c.size() == 10
    await c.clear()
    assert await c.size() == 0


@pytest.mark.asyncio
async def test_prune_expired():
    c = InMemoryCache(default_ttl=0.05)
    await c.set("a", 1)
    await c.set("b", 2, ttl=10)
    await asyncio.sleep(0.1)
    n = await c.prune_expired()
    assert n == 1
    assert await c.get("b") == 2


@pytest.mark.asyncio
async def test_keys():
    c = InMemoryCache()
    await c.set("x", 1)
    await c.set("y", 2)
    keys = await c.keys()
    assert set(keys) == {"x", "y"}


@pytest.mark.asyncio
async def test_get_or_set_sync_factory():
    c = InMemoryCache()
    called = [0]

    def factory():
        called[0] += 1
        return "computed"

    v1 = await c.get_or_set("k", factory=factory)
    v2 = await c.get_or_set("k", factory=factory)
    assert v1 == "computed"
    assert v2 == "computed"
    assert called[0] == 1


@pytest.mark.asyncio
async def test_get_or_set_async_factory():
    c = InMemoryCache()

    async def factory():
        return 99

    v = await c.get_or_set("k", factory=factory)
    assert v == 99
