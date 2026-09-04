"""Зведення котирувань по всіх ринках для однієї назви скіна."""
from __future__ import annotations

import asyncio
import logging

from .sources import Quote

log = logging.getLogger("market")

# лише справжні weapon-кейси (endswith, щоб не чіпляти «Case Hardened» тощо).
# капсули / піни / графіті / music kit box свідомо не входять — /top тільки по кейсах
_CASE_SUFFIX = (" Case",)


class Market:
    def __init__(self, client, depth, ext_sources, steam=None):
        self._client = client
        self._depth = depth
        self._ext = list(ext_sources)
        self.steam = steam

    @property
    def depth(self):
        return self._depth

    @property
    def client(self):
        return self._client

    @property
    def sources(self):
        return self._ext

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
        qs = self.quotes(name)
        return min(qs, key=lambda t: t[2].price) if qs else None

    def summary(self, name: str) -> str:
        return " · ".join(f"{lbl} ${q.price:.2f}" for _, lbl, q in self.quotes(name))

    # ---- /top ----

    def _merged(self):
        """norm -> [(label, Quote)] по всіх ext-ринках."""
        m: dict[str, list] = {}
        for s in self._ext:
            for norm, q in s.items():
                m.setdefault(norm, []).append((s.label, q))
        return m

    @staticmethod
    def _is_case(name: str) -> bool:
        return name.endswith(_CASE_SUFFIX)

    def top_cheapest(self, limit: int = 15, cases_only: bool = True):
        """[(name, label, price)] — найдешевші зараз."""
        rows = []
        for qs in self._merged().values():
            lbl, q = min(qs, key=lambda t: t[1].price)
            if not q.name or q.price < 0.03:
                continue
            if cases_only and not self._is_case(q.name):
                continue
            rows.append((q.name, lbl, q.price))
        rows.sort(key=lambda t: t[2])
        return rows[:limit]

    def case_names(self, limit: int = 120):
        """Назви weapon-кейсів, відомих ext-ринкам, найдешевші перші (для історії/рух-топу)."""
        rows = []
        for qs in self._merged().values():
            _, q = min(qs, key=lambda t: t[1].price)
            if not q.name or q.price < 0.03 or not self._is_case(q.name):
                continue
            rows.append((q.name, q.price))
        rows.sort(key=lambda t: t[1])
        return [n for n, _ in rows[:limit]]

    def top_spread(self, limit: int = 15, cases_only: bool = True):
        """[(name, lo_lbl, lo_price, hi_lbl, hi_price, pct)] — найбільший розкид між ринками."""
        rows = []
        for qs in self._merged().values():
            if len(qs) < 2:
                continue
            lo = min(qs, key=lambda t: t[1].price)
            hi = max(qs, key=lambda t: t[1].price)
            if lo[1].price < 0.05 or hi[1].price <= 0 or not lo[1].name:
                continue
            if cases_only and not self._is_case(lo[1].name):
                continue
            ratio = hi[1].price / lo[1].price
            if ratio > 5:  # 5x+ між ринками — майже завжди сміттєвий лот
                continue
            pct = (hi[1].price - lo[1].price) / hi[1].price * 100
            rows.append((lo[1].name, lo[0], lo[1].price, hi[0], hi[1].price, pct))
        rows.sort(key=lambda t: t[5], reverse=True)
        return rows[:limit]
