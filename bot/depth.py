"""Глибина ринку — скільки лотів по якій ціні — з великого експорту
`api_csgo_full.json` (кожен лот окремим записом).

Файл великий (~1 ГБ, gzip ~160 МБ), тож тягнемо його рідко
(`DEPTH_REFRESH_MIN`, дефолт 15 хв) і лише коли є стеження з `min_qty > 1`.
Парсимо стрімом через ijson: памʼять не росте, зберігаємо тільки ціни
для потрібних назв, згорнуті у «ціна -> кількість».
"""
from __future__ import annotations

import asyncio
import collections
import logging
import time

import httpx
import ijson

log = logging.getLogger("depth")

# якщо індекс молодший за це і вже містить усі потрібні назви — не качаємо повторно
_FRESH_S = 120


class DepthIndex:
    def __init__(self, cfg):
        self._url = cfg.full_export_url
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=180.0, write=10.0, pool=5.0),
            headers={"User-Agent": "lis-price-bot/1.0"},
            follow_redirects=True,
        )
        self._ladders: dict[str, dict[float, int]] = {}  # name -> {price: qty}
        self.updated_at: float = 0.0
        self._etag: str | None = None
        self._indexed: set = set()  # назви, що були в останньому успішному парсингу
        self._lock: asyncio.Lock | None = None

    async def refresh(self, names) -> bool:
        names = {n for n in names if n}
        if not names:
            self._ladders = {}
            self._indexed = set()
            return False
        if self._lock is None:
            self._lock = asyncio.Lock()
        async with self._lock:
            fresh = 0 <= (time.time() - self.updated_at) <= _FRESH_S
            if fresh and names <= self._indexed:
                return True
            return await self._do_refresh(names)

    async def _do_refresh(self, names: set) -> bool:
        # If-None-Match можна слати, тільки якщо всі потрібні назви вже проіндексовані
        headers = {}
        if self._etag and names <= self._indexed:
            headers["If-None-Match"] = self._etag

        counters = {n: collections.Counter() for n in names}

        @ijson.coroutine
        def sink():
            while True:
                item = yield
                c = counters.get(item.get("name"))
                if c is None:
                    continue
                p = item.get("price")
                if p is None:
                    continue
                try:
                    c[round(float(p), 2)] += 1
                except (TypeError, ValueError):
                    pass

        parser = ijson.items_coro(sink(), "items.item")
        try:
            async with self._http.stream("GET", self._url, headers=headers) as r:
                if r.status_code == 304:
                    self.updated_at = time.time()  # дані підтверджено актуальними
                    return True
                if r.status_code != 200:
                    log.warning("full export status %s", r.status_code)
                    return False
                async for chunk in r.aiter_bytes():
                    parser.send(chunk)
            parser.close()
            new_etag = r.headers.get("ETag")
        except httpx.HTTPError as e:
            log.warning("depth fetch failed: %s", e or type(e).__name__)
            return False
        except Exception:
            log.exception("depth parse failed")
            return False

        self._ladders = {n: dict(c) for n, c in counters.items() if c}
        self._indexed = set(names)
        self._etag = new_etag or self._etag
        self.updated_at = time.time()
        log.info("depth updated: %d/%d names", len(self._ladders), len(names))
        return True

    def has(self, name: str) -> bool:
        return name in self._ladders

    def qty_at_or_below(self, name: str, price: float):
        lad = self._ladders.get(name)
        if lad is None:
            return None
        return sum(q for p, q in lad.items() if p <= price + 1e-9)

    def floor(self, name: str):
        lad = self._ladders.get(name)
        return min(lad) if lad else None

    def bulk_floor(self, name: str):
        """Найдешевша ціна з реальним обсягом — перший «товстий» рівень.

        Відсікає поодинокі свіжі/зовнішні лоти на дні (1-30 шт), які на сайті
        ще не видно. Поріг — 1% усіх лотів або 20, що більше.
        """
        lad = self._ladders.get(name)
        if not lad:
            return None
        thr = max(20, sum(lad.values()) // 100)
        fat = [p for p, q in lad.items() if q >= thr]
        return min(fat) if fat else min(lad)

    def count(self, name: str):
        lad = self._ladders.get(name)
        return sum(lad.values()) if lad else None

    def ladder(self, name: str, limit: int = 8):
        lad = self._ladders.get(name)
        if not lad:
            return []
        return sorted(lad.items())[:limit]

    def age_min(self) -> int:
        return int((time.time() - self.updated_at) // 60) if self.updated_at else -1

    async def aclose(self):
        await self._http.aclose()
