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
    buy_order: float = 0.0   # скільки скуповують (bid), якщо ринок віддає
    name: str = ""           # market_hash_name як віддав ринок


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
        self._ok_at = 0.0            # час останнього успішного оновлення
        self._etag: str | None = None
        self._fails = 0  # підряд невдалих спроб -> експоненційний бекоф

    def status(self) -> dict:
        age = int(time.time() - self._ok_at) if self._ok_at else -1
        return {"key": self.key, "items": len(self._by_norm),
                "age_s": age, "fails": self._fails}

    def _cur_interval(self) -> float:
        # після кількох помилок відкладаємо запити (до ~1 год), щоб не спамити
        return self.min_interval * min(2 ** self._fails, 64)

    def _fail(self, msg: str):
        # шумимо в лог лише перші кілька разів, далі тихо бекофимось
        (log.warning if self._fails < 3 else log.debug)("%s %s", self.key, msg)
        self._fails += 1
        self._last = time.time()

    async def refresh(self) -> bool:
        if time.time() - self._last < self._cur_interval():
            return False
        headers = {"If-None-Match": self._etag} if self._etag else {}
        try:
            r = await self._http.get(self._url, headers=headers)
        except httpx.HTTPError as e:
            self._fail(f"fetch failed: {e or type(e).__name__}")
            return False
        if r.status_code == 304:
            self._fails = 0
            self._last = time.time()
            return False
        if r.status_code != 200:
            self._fail(f"status {r.status_code}")
            return False
        try:
            data = self._parse(r.json())
        except Exception:
            self._fail("parse failed")
            return False
        if data:
            self._by_norm = data
            self._etag = r.headers.get("ETag") or self._etag
        self._fails = 0
        self._last = self._ok_at = time.time()
        log.info("%s updated: %d items", self.key, len(self._by_norm))
        return True

    def _parse(self, payload) -> dict:
        raise NotImplementedError

    def lookup(self, lis_name: str) -> Quote | None:
        return self._by_norm.get(normalize(lis_name))

    def items(self):
        return self._by_norm.items()

    def ready(self) -> bool:
        return bool(self._by_norm)

    async def aclose(self):
        await self._http.aclose()


class McsgoSource(_JsonSource):
    key = "mcsgo"
    label = "market.csgo"
    min_interval = 90  # class_instance-фід ~7 МБ

    def _parse(self, payload) -> dict:
        # items — словник classid_instanceid -> {price, buy_order, market_hash_name, ...}
        items = payload.get("items", {})
        rows = items.values() if isinstance(items, dict) else items
        by_name: dict[str, tuple] = {}  # norm -> (price, buy_order, raw_name)
        for it in rows:
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
                bo = float(it.get("buy_order") or 0)
            except (TypeError, ValueError):
                bo = 0.0
            k = normalize(n)
            cur = by_name.get(k)
            if cur is None or price < cur[0]:
                by_name[k] = (price, bo, n)
        return {
            k: Quote(price, 0, f"https://market.csgo.com/en/{quote(rn)}", bo, rn)
            for k, (price, bo, rn) in by_name.items()
        }


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
                0.0, n,
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
