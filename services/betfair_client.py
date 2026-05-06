"""P0-6: скелет клиента Betfair Exchange API (для CLV-метрики).

Зачем: Betfair Exchange — единственный бесплатный источник sharp-money /
closing odds на массовом уровне. Без CLV (closing line value) метрики
любой ROI < 5% — это шум.

Что реализует этот скелет:
- Логин по логину/паролю + application key.
- Логин по сертификату (более стабильный, "Non-interactive").
- ``listEventTypes``, ``listCompetitions``, ``listEvents``,
  ``listMarketCatalogue`` — поиск рынков.
- ``listMarketBook`` — текущие лучшие back/lay цены.
- Логаут.

Тесты: вся HTTP-обвязка пропущена через aiohttp.ClientSession; мокается
через ``aiohttp_responses``-подобный подход. Login flow проверяется
без сети — методы принимают session, который возвращает заранее
заданный JSON.

Замечание: для production нужен сертификат + ключ (см. инструкцию
https://developer.betfair.com/get-started/#non-interactive-bot-login).
Этот клиент — основа, поверх которой добавляются логика снятия closing
line за N минут до старта матча и сохранение в ``services.clv_tracker``.
"""

from __future__ import annotations

import asyncio
import ssl
from dataclasses import dataclass, field
from typing import Any

import aiohttp
from loguru import logger

# Betfair endpoints (Europe). Для AU/нерезидентов отдельный сабдомен.
LOGIN_INTERACTIVE = "https://identitysso.betfair.com/api/login"
LOGIN_NON_INTERACTIVE = (
    "https://identitysso-cert.betfair.com/api/certlogin"
)
LOGOUT = "https://identitysso.betfair.com/api/logout"
KEEP_ALIVE = "https://identitysso.betfair.com/api/keepAlive"
RPC_BASE = (
    "https://api.betfair.com/exchange/betting/json-rpc/v1"
)

# RPC operation names — описание см. в Betfair API-NG docs.
OP_LIST_EVENT_TYPES = "SportsAPING/v1.0/listEventTypes"
OP_LIST_COMPETITIONS = "SportsAPING/v1.0/listCompetitions"
OP_LIST_EVENTS = "SportsAPING/v1.0/listEvents"
OP_LIST_MARKET_CATALOGUE = "SportsAPING/v1.0/listMarketCatalogue"
OP_LIST_MARKET_BOOK = "SportsAPING/v1.0/listMarketBook"


class BetfairAuthError(RuntimeError):
    """Логин не удался."""


class BetfairAPIError(RuntimeError):
    """Betfair вернул ошибку JSON-RPC."""


@dataclass(slots=True)
class BetfairSession:
    """Хранит токен сессии + application key."""

    app_key: str
    session_token: str
    expires_at_monotonic: float = 0.0
    last_keep_alive: float = 0.0
    _lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def headers(self) -> dict[str, str]:
        return {
            "X-Application": self.app_key,
            "X-Authentication": self.session_token,
            "Content-Type": "application/json",
            "Accept": "application/json",
        }


class BetfairClient:
    """Async-клиент Betfair Exchange.

    Минимальный набор для CLV-трекера: логин, listMarketBook,
    listMarketCatalogue. Остальное — расширяется по мере необходимости.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        *,
        app_key: str,
        username: str | None = None,
        password: str | None = None,
        cert_pem_path: str | None = None,
        cert_key_path: str | None = None,
        timeout: float = 20.0,
    ) -> None:
        self._session = session
        self._app_key = app_key
        self._username = username
        self._password = password
        self._cert_pem_path = cert_pem_path
        self._cert_key_path = cert_key_path
        self._timeout = aiohttp.ClientTimeout(total=timeout)
        self._bf_session: BetfairSession | None = None

    # ─── Auth ────────────────────────────────────────────────────────────

    async def login(self) -> BetfairSession:
        """Логинит клиента. Если есть cert + key, использует non-interactive."""
        if self._cert_pem_path and self._cert_key_path:
            return await self._login_non_interactive()
        if self._username and self._password:
            return await self._login_interactive()
        raise BetfairAuthError(
            "Нужны либо username+password, либо cert_pem_path+cert_key_path"
        )

    async def _login_interactive(self) -> BetfairSession:
        assert self._username and self._password
        headers = {
            "X-Application": self._app_key,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        }
        data = {"username": self._username, "password": self._password}
        async with self._session.post(
            LOGIN_INTERACTIVE,
            headers=headers,
            data=data,
            timeout=self._timeout,
        ) as resp:
            payload = await resp.json(content_type=None)
        return self._handle_login_response(payload, key="token")

    async def _login_non_interactive(self) -> BetfairSession:
        assert self._cert_pem_path and self._cert_key_path
        ctx = ssl.create_default_context()
        ctx.load_cert_chain(self._cert_pem_path, self._cert_key_path)
        connector = aiohttp.TCPConnector(ssl=ctx)
        # Создаём отдельную ClientSession с TLS-сертификатом — обычная
        # сессия не имеет mTLS-контекста.
        async with aiohttp.ClientSession(
            connector=connector, timeout=self._timeout
        ) as ssl_session:
            headers = {
                "X-Application": self._app_key,
                "Content-Type": "application/x-www-form-urlencoded",
            }
            data = {
                "username": self._username or "",
                "password": self._password or "",
            }
            async with ssl_session.post(
                LOGIN_NON_INTERACTIVE,
                headers=headers,
                data=data,
            ) as resp:
                payload = await resp.json(content_type=None)
        return self._handle_login_response(payload, key="sessionToken")

    def _handle_login_response(
        self, payload: dict[str, Any], *, key: str
    ) -> BetfairSession:
        status = (payload or {}).get("status") or (payload or {}).get("loginStatus")
        if status not in ("SUCCESS", None):
            raise BetfairAuthError(f"Betfair login failed: {status}")
        token = (payload or {}).get(key)
        if not token:
            raise BetfairAuthError(
                f"Betfair login: токен '{key}' отсутствует в ответе: {payload}"
            )
        bf = BetfairSession(
            app_key=self._app_key,
            session_token=str(token),
        )
        self._bf_session = bf
        logger.info("Betfair login OK (token len={})", len(bf.session_token))
        return bf

    async def logout(self) -> None:
        if self._bf_session is None:
            return
        try:
            async with self._session.post(
                LOGOUT,
                headers=self._bf_session.headers,
                timeout=self._timeout,
            ):
                pass
        finally:
            self._bf_session = None

    async def keep_alive(self) -> None:
        if self._bf_session is None:
            return
        async with self._session.post(
            KEEP_ALIVE,
            headers=self._bf_session.headers,
            timeout=self._timeout,
        ) as resp:
            payload = await resp.json(content_type=None)
        if (payload or {}).get("status") != "SUCCESS":
            raise BetfairAuthError(f"Betfair keepAlive failed: {payload}")

    # ─── RPC ──────────────────────────────────────────────────────────────

    async def _rpc(self, method: str, params: dict[str, Any]) -> Any:
        if self._bf_session is None:
            raise BetfairAuthError("Сначала вызови login()")
        body = [
            {
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
                "id": 1,
            }
        ]
        async with self._session.post(
            RPC_BASE,
            headers=self._bf_session.headers,
            json=body,
            timeout=self._timeout,
        ) as resp:
            payload = await resp.json(content_type=None)
        if not isinstance(payload, list) or not payload:
            raise BetfairAPIError(f"Betfair RPC: пустой ответ {payload!r}")
        first = payload[0]
        if "error" in first:
            raise BetfairAPIError(f"Betfair RPC: {first['error']}")
        return first.get("result")

    async def list_event_types(
        self, filter_: dict[str, Any] | None = None
    ) -> list[dict[str, Any]]:
        result = await self._rpc(
            OP_LIST_EVENT_TYPES,
            {"filter": filter_ or {}},
        )
        return list(result or [])

    async def list_events(
        self,
        *,
        event_type_ids: list[str] | None = None,
        market_start_time: dict[str, str] | None = None,
        text_query: str | None = None,
    ) -> list[dict[str, Any]]:
        f: dict[str, Any] = {}
        if event_type_ids:
            f["eventTypeIds"] = event_type_ids
        if market_start_time:
            f["marketStartTime"] = market_start_time
        if text_query:
            f["textQuery"] = text_query
        return list(await self._rpc(OP_LIST_EVENTS, {"filter": f}) or [])

    async def list_market_catalogue(
        self,
        *,
        event_ids: list[str] | None = None,
        market_type_codes: list[str] | None = None,
        max_results: int = 50,
        market_projection: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        f: dict[str, Any] = {}
        if event_ids:
            f["eventIds"] = event_ids
        if market_type_codes:
            f["marketTypeCodes"] = market_type_codes
        params: dict[str, Any] = {
            "filter": f,
            "maxResults": str(max_results),
        }
        if market_projection:
            params["marketProjection"] = market_projection
        return list(
            await self._rpc(OP_LIST_MARKET_CATALOGUE, params) or []
        )

    async def list_market_book(
        self,
        market_ids: list[str],
        *,
        price_projection: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"marketIds": market_ids}
        if price_projection is not None:
            params["priceProjection"] = price_projection
        return list(await self._rpc(OP_LIST_MARKET_BOOK, params) or [])


__all__ = [
    "KEEP_ALIVE",
    "LOGIN_INTERACTIVE",
    "LOGIN_NON_INTERACTIVE",
    "LOGOUT",
    "RPC_BASE",
    "BetfairAPIError",
    "BetfairAuthError",
    "BetfairClient",
    "BetfairSession",
]
