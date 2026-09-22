"""Регресія на реальний баг: комбінований запит кількома names[] губив дешеві
лоти однієї з назв. Фікс - окремий запит на кожну назву; перевіряємо саме це,
через httpx.MockTransport (без справжньої мережі)."""
import asyncio

import httpx

from bot.lis_search import LisSearchClient


def test_fetch_names_queries_each_name_in_its_own_request():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        names = request.url.params.get_list("names[]")
        seen.append(names)
        name = names[0]
        return httpx.Response(200, json={
            "data": [{"id": 1, "name": name, "price": 0.19}],
            "meta": {"per_page": 200, "next_cursor": None},
        })

    async def go():
        client = LisSearchClient("key")
        client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            out = await client.fetch_names(["Recoil Case", "Revolution Case"])
        finally:
            await client.aclose()
        assert seen == [["Recoil Case"], ["Revolution Case"]]  # НЕ одним запитом разом
        assert out == {"Recoil Case": {1: 0.19}, "Revolution Case": {1: 0.19}}

    asyncio.run(go())


def test_fetch_names_omits_name_whose_request_failed():
    def handler(request: httpx.Request) -> httpx.Response:
        name = request.url.params.get("names[]")
        if name == "Broken Case":
            return httpx.Response(500, json={"message": "boom"})
        return httpx.Response(200, json={
            "data": [{"id": 1, "name": name, "price": 0.19}],
            "meta": {"per_page": 200},
        })

    async def go():
        client = LisSearchClient("key")
        client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            out = await client.fetch_names(["Good Case", "Broken Case"])
        finally:
            await client.aclose()
        # Broken Case ВІДСУТНЯ ключем, а не {} - реконсилер не має права
        # прочитати це як "лотів нема" і стерти живий кеш нулем
        assert out == {"Good Case": {1: 0.19}}
        assert "Broken Case" not in out

    asyncio.run(go())


def test_fetch_name_single():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "data": [
                {"id": 2, "name": "Revolution Case", "price": 0.22},
                {"id": 1, "name": "Revolution Case", "price": 0.19},
            ],
            "meta": {"per_page": 200},
        })

    async def go():
        client = LisSearchClient("key")
        client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            lots = await client.fetch_name("Revolution Case")
        finally:
            await client.aclose()
        assert lots == {2: 0.22, 1: 0.19}

    asyncio.run(go())


def test_fetch_name_paginates_within_single_name_until_no_cursor():
    # регресія на реальний випадок: 333 лоти під ціллю - більше однієї
    # сторінки (200), для ОДНІЄЇ назви пагінація має продовжуватись
    pages = [
        {"data": [{"id": i, "name": "Revolution Case", "price": 0.18} for i in range(200)],
         "meta": {"per_page": 200, "next_cursor": "p2"}},
        {"data": [{"id": i, "name": "Revolution Case", "price": 0.19} for i in range(200, 333)],
         "meta": {"per_page": 200, "next_cursor": None}},
    ]
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.params.get("cursor"))
        return httpx.Response(200, json=pages[len(calls) - 1])

    async def go():
        client = LisSearchClient("key")
        client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            lots = await client.fetch_name("Revolution Case")
        finally:
            await client.aclose()
        assert len(lots) == 333
        assert calls == [None, "p2"]

    asyncio.run(go())


def test_fetch_name_stops_at_max_pages_safety_cap():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "data": [{"id": 1, "name": "X", "price": 0.1}],
            "meta": {"per_page": 200, "next_cursor": "always_more"},  # ніби нескінченно
        })

    async def go():
        client = LisSearchClient("key")
        client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        try:
            lots = await client.fetch_name("X", max_pages=3)
        finally:
            await client.aclose()
        assert lots == {1: 0.1}  # не зациклилось назавжди

    asyncio.run(go())
