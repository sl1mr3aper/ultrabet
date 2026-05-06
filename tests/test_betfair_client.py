"""Тесты services/betfair_client — login + RPC через локальный aiohttp."""

from __future__ import annotations

from typing import Any

import aiohttp
import pytest
from aiohttp import web

from services import betfair_client as bf


@pytest.fixture
async def fake_betfair() -> Any:
    """Локальный stub login + json-rpc."""
    state = {"login_calls": 0, "rpc_calls": 0, "logout_calls": 0}

    async def login(request: web.Request) -> web.Response:
        state["login_calls"] += 1
        data = await request.post()
        if data.get("username") == "u" and data.get("password") == "p":
            return web.json_response({"status": "SUCCESS", "token": "tok-123"})
        return web.json_response({"status": "FAIL"})

    async def rpc(request: web.Request) -> web.Response:
        state["rpc_calls"] += 1
        body = await request.json()
        op = body[0]["method"]
        if op.endswith("listEventTypes"):
            return web.json_response(
                [{"id": 1, "result": [{"eventType": {"id": "1"}}]}]
            )
        if op.endswith("listMarketBook"):
            return web.json_response(
                [
                    {
                        "id": 1,
                        "result": [
                            {
                                "marketId": "1.234",
                                "runners": [
                                    {"selectionId": 11, "lastPriceTraded": 1.85}
                                ],
                            }
                        ],
                    }
                ]
            )
        return web.json_response([{"id": 1, "error": {"code": -1}}])

    async def logout(request: web.Request) -> web.Response:
        state["logout_calls"] += 1
        return web.json_response({"status": "SUCCESS"})

    app = web.Application()
    app.router.add_post("/login", login)
    app.router.add_post("/rpc", rpc)
    app.router.add_post("/logout", logout)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 0)
    await site.start()
    port = site._server.sockets[0].getsockname()[1]  # type: ignore[union-attr]
    base = f"http://127.0.0.1:{port}"
    try:
        yield {"base": base, "state": state}
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_login_interactive_success(
    monkeypatch: pytest.MonkeyPatch, fake_betfair: Any
) -> None:
    monkeypatch.setattr(bf, "LOGIN_INTERACTIVE", f"{fake_betfair['base']}/login")
    async with aiohttp.ClientSession() as session:
        client = bf.BetfairClient(
            session,
            app_key="APP-1",
            username="u",
            password="p",
        )
        bf_session = await client.login()
    assert bf_session.session_token == "tok-123"
    assert fake_betfair["state"]["login_calls"] == 1


@pytest.mark.asyncio
async def test_login_failure_raises(
    monkeypatch: pytest.MonkeyPatch, fake_betfair: Any
) -> None:
    monkeypatch.setattr(bf, "LOGIN_INTERACTIVE", f"{fake_betfair['base']}/login")
    async with aiohttp.ClientSession() as session:
        client = bf.BetfairClient(
            session,
            app_key="APP-1",
            username="wrong",
            password="wrong",
        )
        with pytest.raises(bf.BetfairAuthError):
            await client.login()


@pytest.mark.asyncio
async def test_login_without_credentials_raises() -> None:
    async with aiohttp.ClientSession() as session:
        client = bf.BetfairClient(session, app_key="APP-1")
        with pytest.raises(bf.BetfairAuthError):
            await client.login()


@pytest.mark.asyncio
async def test_rpc_requires_login() -> None:
    async with aiohttp.ClientSession() as session:
        client = bf.BetfairClient(
            session, app_key="APP-1", username="u", password="p"
        )
        with pytest.raises(bf.BetfairAuthError):
            await client.list_event_types()


@pytest.mark.asyncio
async def test_list_market_book(
    monkeypatch: pytest.MonkeyPatch, fake_betfair: Any
) -> None:
    monkeypatch.setattr(bf, "LOGIN_INTERACTIVE", f"{fake_betfair['base']}/login")
    monkeypatch.setattr(bf, "RPC_BASE", f"{fake_betfair['base']}/rpc")
    async with aiohttp.ClientSession() as session:
        client = bf.BetfairClient(
            session, app_key="APP-1", username="u", password="p"
        )
        await client.login()
        books = await client.list_market_book(["1.234"])
    assert len(books) == 1
    assert books[0]["marketId"] == "1.234"
    assert books[0]["runners"][0]["lastPriceTraded"] == 1.85


@pytest.mark.asyncio
async def test_list_event_types(
    monkeypatch: pytest.MonkeyPatch, fake_betfair: Any
) -> None:
    monkeypatch.setattr(bf, "LOGIN_INTERACTIVE", f"{fake_betfair['base']}/login")
    monkeypatch.setattr(bf, "RPC_BASE", f"{fake_betfair['base']}/rpc")
    async with aiohttp.ClientSession() as session:
        client = bf.BetfairClient(
            session, app_key="APP-1", username="u", password="p"
        )
        await client.login()
        out = await client.list_event_types()
    assert isinstance(out, list)
    assert out[0]["eventType"]["id"] == "1"


@pytest.mark.asyncio
async def test_logout_clears_session(
    monkeypatch: pytest.MonkeyPatch, fake_betfair: Any
) -> None:
    monkeypatch.setattr(bf, "LOGIN_INTERACTIVE", f"{fake_betfair['base']}/login")
    monkeypatch.setattr(bf, "LOGOUT", f"{fake_betfair['base']}/logout")
    async with aiohttp.ClientSession() as session:
        client = bf.BetfairClient(
            session, app_key="APP-1", username="u", password="p"
        )
        await client.login()
        assert client._bf_session is not None
        await client.logout()
        assert client._bf_session is None
    assert fake_betfair["state"]["logout_calls"] == 1
