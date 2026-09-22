"""WS-клієнт lis-skins (Centrifugo) — тримає LisCache свіжим подіями `public:obtained-skins`.

Мережевий шар навмисно тонкий і без юніт-тестів (як LisClient/DepthIndex) —
розбір самих подій винесено в lis_events.parse_market_event, там і тести.
Перепідключення при обриві — вбудоване в бібліотеку centrifuge-python.
"""
from __future__ import annotations

import logging

import httpx
from centrifuge import (
    Client,
    ClientEventHandler,
    ConnectedContext,
    ConnectingContext,
    DisconnectedContext,
    ErrorContext,
    PublicationContext,
    SubscriptionErrorContext,
    SubscriptionEventHandler,
)

from .lis_events import parse_market_event

log = logging.getLogger("lis_ws")

WS_URL = "wss://ws.lis-skins.com/connection/websocket"
TOKEN_URL = "https://api.lis-skins.com/v1/user/get-ws-token"
CHANNEL = "public:obtained-skins"


class _ClientEvents(ClientEventHandler):
    async def on_connecting(self, ctx: ConnectingContext) -> None:
        log.info("lis WS: connecting")

    async def on_connected(self, ctx: ConnectedContext) -> None:
        log.info("lis WS: connected")

    async def on_disconnected(self, ctx: DisconnectedContext) -> None:
        log.warning("lis WS: disconnected (%s)", ctx)

    async def on_error(self, ctx: ErrorContext) -> None:
        log.warning("lis WS: client error (%s)", ctx)


class _SubEvents(SubscriptionEventHandler):
    def __init__(self, cache) -> None:
        self._cache = cache

    async def on_publication(self, ctx: PublicationContext) -> None:
        parsed = parse_market_event(ctx.pub.data)
        if parsed is None:
            return
        kind, name, lot_id, price = parsed
        if kind == "upsert":
            self._cache.upsert(name, lot_id, price)
        else:
            self._cache.remove(name, lot_id)

    async def on_error(self, ctx: SubscriptionErrorContext) -> None:
        log.warning("lis WS: subscription error (%s)", ctx)


class LisWsClient:
    """Одне постійне WS-зʼєднання на весь ринок; наповнює LisCache в реальному часі."""

    def __init__(self, api_key: str, cache, ws_url: str = WS_URL, token_url: str = TOKEN_URL):
        self._key = api_key
        self._cache = cache
        self._ws_url = ws_url
        self._token_url = token_url
        self._http = httpx.AsyncClient(timeout=15.0)
        self._client: Client | None = None

    async def _get_token(self) -> str:
        resp = await self._http.get(
            self._token_url,
            headers={"Authorization": f"Bearer {self._key}", "Accept": "application/json"},
        )
        resp.raise_for_status()
        return resp.json()["data"]["token"]

    async def start(self) -> None:
        """Підключитись і підписатись на канал. Викликати раз при старті бота."""
        self._client = Client(self._ws_url, events=_ClientEvents(), get_token=self._get_token)
        sub = self._client.new_subscription(CHANNEL, events=_SubEvents(self._cache))
        await self._client.connect()
        await sub.subscribe()

    async def aclose(self) -> None:
        if self._client is not None:
            try:
                await self._client.disconnect()
            except Exception:
                log.warning("lis WS: disconnect on shutdown failed", exc_info=True)
        await self._http.aclose()
