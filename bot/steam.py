"""Ціна зі Steam Community Market — лінива, по одному айтему, з кешем.

Steam не має балку й жорстко лімітує, тож тягнемо ціну лише коли її реально
показуємо (картка / порівняння) і кешуємо на кілька годин. Помилки — тихо None.
"""
from __future__ import annotations

import asyncio
import logging
import time

import httpx

log = logging.getLogger("steam")

_TTL = 6 * 3600        # кеш на 6 год
_NEG_TTL = 30 * 60     # невдачу теж кешуємо ненадовго
_MIN_GAP = 2.0         # мін. пауза між запитами до Steam


def _to_float(s):
    if not s:
        return None
    s = s.strip().lstrip("$").replace(",", "").replace("\xa0", "")
    try:
        return float(s)
    except ValueError:
        return None


class SteamPrices:
    def __init__(self, enabled: bool = True, currency: int = 1, appid: int = 730):
        self.enabled = enabled
        self._url = "https://steamcommunity.com/market/priceoverview/"
        self._cur, self._app = currency, appid
        self._cache: dict[str, tuple[float, float | None]] = {}  # name -> (ts, price)
        self._lock = asyncio.Lock()
        self._last_req = 0.0
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=8.0, read=12.0, write=8.0, pool=5.0),
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"},
            follow_redirects=True,
        )

    async def get(self, name: str):
        if not self.enabled or not name:
            return None
        hit = self._cache.get(name)
        now = time.time()
        if hit is not None:
            ts, price = hit
            if now - ts < (_TTL if price is not None else _NEG_TTL):
                return price
        async with self._lock:
            hit = self._cache.get(name)  # могли оновити поки чекали лок
            if hit is not None and time.time() - hit[0] < (_TTL if hit[1] is not None else _NEG_TTL):
                return hit[1]
            gap = time.time() - self._last_req
            if gap < _MIN_GAP:
                await asyncio.sleep(_MIN_GAP - gap)
            price = await self._fetch(name)
            self._last_req = time.time()
            self._cache[name] = (time.time(), price)
            return price

    async def _fetch(self, name: str):
        params = {"appid": self._app, "currency": self._cur,
                  "market_hash_name": name}
        try:
            r = await self._http.get(self._url, params=params)
        except httpx.HTTPError as e:
            log.debug("steam fetch failed: %s", e)
            return None
        if r.status_code != 200:
            log.debug("steam status %s for %s", r.status_code, name)
            return None
        try:
            d = r.json()
        except ValueError:
            return None
        if not d.get("success"):
            return None
        return _to_float(d.get("lowest_price")) or _to_float(d.get("median_price"))

    async def aclose(self):
        await self._http.aclose()
