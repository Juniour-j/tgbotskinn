"""Search API lis-skins (`GET /v1/market/search`) — бекфіл і періодична звірка LisCache.

За рекомендацією самого lis-skins search відстає на кілька хвилин, як і сайт —
для миттєвих сповіщень не годиться, тут він лише наповнює кеш при старті бота
й лікує його, якщо WebSocket-з'єднання перервалось.

ВАЖЛИВО: один запит на назву, НЕ пакетом кількох `names[]` в одному виклику.
`sort_by=lowest_price` сортує лоти ВСІХ переданих назв РАЗОМ - якщо одна назва
має купу дешевих лотів, вона займає всі перші сторінки, а інша не влазить у
ліміт і виглядає так, ніби в неї нуль лотів (хоча насправді просто не
"дотягнулась" по курсору). З окремим запитом на назву такого перекосу нема.
Однієї сторінки (200 найдешевших) вистачає і на показ ціни, і на майбутню
купівлю до 100 лотів.
"""
from __future__ import annotations

import logging

import httpx

log = logging.getLogger("lis_search")

SEARCH_URL = "https://api.lis-skins.com/v1/market/search"


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
    (як і в LisClient/DepthIndex), перевіряється живим смоук-запуском.
    Виняток: fetch_names її ізоляція по назвах — це і є фікс реального бага,
    покритий тестами через httpx.MockTransport (без справжньої мережі)."""

    def __init__(self, api_key: str, timeout: float = 15.0, base_url: str = SEARCH_URL):
        self._key = api_key
        self._url = base_url
        self._http = httpx.AsyncClient(timeout=timeout)

    async def fetch_name(self, name: str, game: str = "csgo") -> dict:
        """{id лота: ціна} для ОДНІЄЇ назви, одна сторінка (200 найдешевших)."""
        params = [("game", game), ("sort_by", "lowest_price"),
                  ("only_unlocked", "1"), ("names[]", name)]
        headers = {"Authorization": f"Bearer {self._key}", "Accept": "application/json"}
        resp = await self._http.get(self._url, params=params, headers=headers)
        resp.raise_for_status()
        return parse_search_page(resp.json()).get(name, {})

    async def fetch_names(self, names, game: str = "csgo") -> dict:
        """{назва: {id: ціна}} - окремий запит на кожну назву.

        Назва, чий запит впав, ПРОСТО ВІДСУТНЯ в результаті (а не {}) - викликач
        (реконсилер) не має права сплутати "запит впав" з "лотів справді нема"
        і затерти нею живий WS-кеш."""
        out: dict = {}
        for name in list(names):
            try:
                out[name] = await self.fetch_name(name, game)
            except httpx.HTTPError:
                log.warning("search fetch failed for %r, лишаю як є", name, exc_info=True)
        return out

    async def aclose(self) -> None:
        await self._http.aclose()
