"""Search API lis-skins (`GET /v1/market/search`) — бекфіл і періодична звірка LisCache.

За рекомендацією самого lis-skins search відстає на кілька хвилин, як і сайт —
для миттєвих сповіщень не годиться, тут він лише наповнює кеш при старті бота
й лікує його, якщо WebSocket-з'єднання перервалось.
"""
from __future__ import annotations

import logging

import httpx

log = logging.getLogger("lis_search")

SEARCH_URL = "https://api.lis-skins.com/v1/market/search"
_PAGE_LIMIT = 5  # запобіжник від нескінченної пагінації при дивній відповіді


def parse_search_page(payload: dict) -> dict:
    """Одна сторінка відповіді search -> {назва: {id лота: ціна}}."""
    out: dict = {}
    for row in payload.get("data") or []:
        name = row.get("name")
        if not name:
            continue
        try:
            lot_id = int(row["id"])
            price = float(row["price"])
        except (KeyError, TypeError, ValueError):
            continue
        out.setdefault(name, {})[lot_id] = price
    return out


def next_cursor(payload: dict):
    """meta.next_cursor або None, якщо сторінок більше нема."""
    return (payload.get("meta") or {}).get("next_cursor") or None


class LisSearchClient:
    """Тонка обгортка над search API — мережевий код навмисно без юніт-тестів
    (як і в LisClient/DepthIndex), перевіряється живим смоук-запуском."""

    def __init__(self, api_key: str, timeout: float = 15.0, base_url: str = SEARCH_URL):
        self._key = api_key
        self._url = base_url
        self._http = httpx.AsyncClient(timeout=timeout)

    async def fetch_names(self, names, game: str = "csgo") -> dict:
        """{назва: {id лота: ціна}} для списку назв (пагінація до _PAGE_LIMIT сторінок)."""
        names = list(names)
        if not names:
            return {}
        merged: dict = {}
        cursor = None
        headers = {"Authorization": f"Bearer {self._key}", "Accept": "application/json"}
        for page in range(_PAGE_LIMIT):
            params = [("game", game), ("sort_by", "lowest_price"), ("only_unlocked", "1")]
            params += [("names[]", n) for n in names]
            if cursor:
                params.append(("cursor", cursor))
            try:
                resp = await self._http.get(self._url, params=params, headers=headers)
                resp.raise_for_status()
            except httpx.HTTPError:
                if page == 0:
                    # перша сторінка не пройшла - весь запит невдалий. Кидаємо далі,
                    # а не повертаємо {}: викликач (реконсилер) не має право сплутати
                    # "запит впав" із "лотів справді нема" і затерти нею живий WS-кеш.
                    raise
                log.warning("search fetch failed on page %d, using partial result", page,
                           exc_info=True)
                break
            payload = resp.json()
            for name, lots in parse_search_page(payload).items():
                merged.setdefault(name, {}).update(lots)
            cursor = next_cursor(payload)
            if not cursor:
                break
        return merged

    async def aclose(self) -> None:
        await self._http.aclose()
