"""Зведення котирувань по всіх ринках для однієї назви скіна."""
from __future__ import annotations

import asyncio
import logging

from .sources import Quote

log = logging.getLogger("market")


class Market:
    def __init__(self, client, depth, ext_sources):
        self._client = client
        self._depth = depth
        self._ext = list(ext_sources)

    @property
    def depth(self):
        return self._depth

    @property
    def client(self):
        return self._client

    async def refresh(self):
        for s in self._ext:
            try:
                await s.refresh()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("%s refresh failed", s.key)

    def _lis_quote(self, name: str):
        sp = self._depth.site_price(name)
        item = self._client.lookup(name)
        url = item.url if item is not None else ""
        if sp is not None:
            return Quote(sp, self._depth.count(name) or 0, url)
        if item is not None:
            return Quote(item.price, item.count, url)
        return None

    def quotes(self, name: str):
        """[(key, label, Quote)] по всіх ринках, де є ціна; lis-skins перший."""
        res = []
        q = self._lis_quote(name)
        if q is not None:
            res.append(("lis", "lis-skins", q))
        for s in self._ext:
            qq = s.lookup(name)
            if qq is not None:
                res.append((s.key, s.label, qq))
        return res

    def best(self, name: str):
        """(key, label, Quote) з найнижчою ціною або None."""
        qs = self.quotes(name)
        return min(qs, key=lambda t: t[2].price) if qs else None

    def summary(self, name: str) -> str:
        """`lis $0.40 · mcsgo $0.38 · skinport $0.41` (порожньо якщо ніде нема)."""
        return " · ".join(f"{lbl} ${q.price:.2f}" for _, lbl, q in self.quotes(name))
