"""Зовнішні ринки (крім lis-skins): market.csgo.com, Skinport.

Кожне джерело тягне свій прайс-JSON і віддає котирування за нормалізованою
назвою скіна (Steam market_hash_name ≈ назва lis-skins для кейсів/капсул).
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from urllib.parse import quote

import httpx

from .matcher import normalize

log = logging.getLogger("sources")


@dataclass(frozen=True)
class Quote:
    price: float
    qty: int
    url: str


class _JsonSource:
    key = ""
    label = ""
    min_interval = 60  # секунд між реальними запитами

    extra_headers: dict = {}

    def __init__(self, url: str, timeout: float = 30.0):
        self._url = url
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=timeout, write=10.0, pool=5.0),
            headers={"User-Agent": "lis-price-bot/1.0",
                     "Accept": "application/json", **self.extra_headers},
            follow_redirects=True,
        )
        self._by_norm: dict[str, Quote] = {}
        self._last = 0.0
        self._etag: str | None = None

    async def refresh(self) -> bool:
        if time.time() - self._last < self.min_interval:
            return False
        headers = {"If-None-Match": self._etag} if self._etag else {}
        try:
            r = await self._http.get(self._url, headers=headers)
        except httpx.HTTPError as e:
            log.warning("%s fetch failed: %s", self.key, e or type(e).__name__)
            return False
        if r.status_code == 304:
            self._last = time.time()
            return False
        if r.status_code != 200:
            log.warning("%s status %s", self.key, r.status_code)
            self._last = time.time()
            return False
        try:
            data = self._parse(r.json())
        except Exception:
            log.exception("%s parse failed", self.key)
            return False
        if data:
            self._by_norm = data
            self._etag = r.headers.get("ETag") or self._etag
        self._last = time.time()
        log.info("%s updated: %d items", self.key, len(self._by_norm))
        return True

    def _parse(self, payload) -> dict:
        raise NotImplementedError

    def lookup(self, lis_name: str) -> Quote | None:
        return self._by_norm.get(normalize(lis_name))

    def ready(self) -> bool:
        return bool(self._by_norm)

    async def aclose(self):
        await self._http.aclose()


class McsgoSource(_JsonSource):
    key = "mcsgo"
    label = "market.csgo"
    min_interval = 60

    def _parse(self, payload) -> dict:
        out: dict[str, Quote] = {}
        for it in payload.get("items", []):
            n = it.get("market_hash_name")
            if not n:
                continue
            try:
                price = float(it["price"])
            except (KeyError, TypeError, ValueError):
                continue
            if price <= 0:
                continue
            try:
                vol = int(float(it.get("volume") or 0))
            except (TypeError, ValueError):
                vol = 0
            out[normalize(n)] = Quote(price, vol,
                                      f"https://market.csgo.com/en/{quote(n)}")
        return out


class SkinportSource(_JsonSource):
    key = "skinport"
    label = "skinport"
    min_interval = 320  # Skinport ліміт ~8 запитів / 5 хв
    extra_headers = {"Accept-Encoding": "br, gzip"}  # без br Skinport віддає 406

    def _parse(self, payload) -> dict:
        out: dict[str, Quote] = {}
        for it in payload:
            n = it.get("market_hash_name")
            p = it.get("min_price")
            if not n or p is None:
                continue
            try:
                price = float(p)
            except (TypeError, ValueError):
                continue
            if price <= 0:
                continue
            out[normalize(n)] = Quote(
                price,
                int(it.get("quantity") or 0),
                it.get("item_page") or "https://skinport.com",
            )
        return out


def build_sources(cfg) -> list:
    """Список увімкнених зовнішніх джерел за cfg.sources."""
    out = []
    for key in cfg.sources:
        if key == "mcsgo":
            out.append(McsgoSource(cfg.mcsgo_url, cfg.http_timeout))
        elif key == "skinport":
            out.append(SkinportSource(cfg.skinport_url, cfg.http_timeout))
    return out
