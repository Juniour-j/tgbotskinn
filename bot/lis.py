"""Клієнт до безкоштовного прайс-експорту lis-skins.com.

Тягне JSON (`csgo.json` за замовчуванням) з підтримкою gzip та ETag:
якщо файл не змінився — сервер віддає 304 і ми нічого не парсимо.

Парсинг (кілька МБ JSON) виконується в окремому потоці через asyncio.to_thread,
щоб не блокувати event loop — інакше бот на час парсингу не відповідає в Telegram.
"""
from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass

import httpx

log = logging.getLogger("lis")


@dataclass
class Item:
    name: str
    price: float
    unlocked_price: float
    url: str
    count: int


def _parse(raw: bytes) -> tuple[dict[str, Item], int]:
    """CPU-робота: розбір JSON + побудова каталогу. Викликається в потоці."""
    payload = json.loads(raw)
    rows = payload if isinstance(payload, list) else payload.get("items", [])
    catalog: dict[str, Item] = {}
    for it in rows:
        name = it.get("name")
        if not name:
            continue
        try:
            price = float(it["price"])
        except (KeyError, TypeError, ValueError):
            continue
        catalog[name] = Item(
            name=name,
            price=price,
            unlocked_price=float(it.get("unlocked_price") or price),
            url=it.get("url", ""),
            count=int(it.get("count") or 0),
        )
    last_update = 0
    if isinstance(payload, dict):
        last_update = int(payload.get("last_update") or 0)
    return catalog, last_update


class LisClient:
    def __init__(self, cfg):
        self._url = cfg.lis_export_url
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=cfg.http_timeout, write=10.0, pool=5.0),
            headers={"User-Agent": "lis-price-bot/1.0"},
            follow_redirects=True,
        )
        self._etag: str | None = None
        self._catalog: dict[str, Item] = {}
        self.last_update = 0

    async def refresh(self) -> bool:
        """True — каталог оновлено; False — без змін / помилка (старі дані лишаються)."""
        headers = {"If-None-Match": self._etag} if self._etag else {}
        try:
            r = await self._http.get(self._url, headers=headers)
        except httpx.HTTPError as e:
            log.warning("fetch failed: %s", e)
            return False

        if r.status_code == 304:
            return False
        if r.status_code != 200:
            log.warning("unexpected status %s", r.status_code)
            return False

        try:
            catalog, last_update = await asyncio.to_thread(_parse, r.content)
        except ValueError:
            log.warning("bad json in export")
            return False

        if not catalog:
            log.warning("empty catalog, keeping previous (%d)", len(self._catalog))
            return False

        self._catalog = catalog
        self._etag = r.headers.get("ETag") or self._etag
        self.last_update = last_update or self.last_update
        log.info("catalog updated: %d skins", len(catalog))
        return True

    def ready(self) -> bool:
        return bool(self._catalog)

    @property
    def names(self):
        return list(self._catalog.keys())

    def lookup(self, name: str) -> Item | None:
        return self._catalog.get(name)

    async def aclose(self):
        await self._http.aclose()
