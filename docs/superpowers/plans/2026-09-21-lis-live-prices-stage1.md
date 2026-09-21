# Свіжа ціна lis-skins через search API (етап 1) — план впровадження

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ціна lis-skins для звичайних стежень береться з `GET /v1/market/search` (найдешевший видимий лот) замість регулярного скачування експорту ~160 МБ; експорт лишається лише для оптових (`x<шт>`) стежень і разових запитів `📊 Глибина`.

**Architecture:** Новий клієнт `LisApi` (з лімітом швидкості, обробкою 429/401) → кеш `LisPrices` (ціна за назвою + цикл оновлення) → `Market._lis_quote` бере ціну з кешу першим пріоритетом, з fallback на експорт і `csgo.json`. Логіка `_cycle` поллера виноситься в клас `Evaluator` з одним `Lock`, щоб після оновлення ціни назви її стеження перевірялись одразу, без подвійних сповіщень. Без `LIS_API_KEY` бот працює як зараз.

**Tech Stack:** Python 3.12, httpx, aiosqlite, aiogram 3.31 (вже в проєкті); тести — pytest + `aiohttp.test_utils.TestServer` (aiohttp уже залежність aiogram). Нових залежностей немає.

**Spec:** `docs/superpowers/specs/2026-09-21-lis-live-prices-design.md` (розділи 4, 6, 7, 8, 9). Етап 2 (WebSocket) — **окремий план**, його пишемо після живої перевірки етапу 1 (формат подій і збіг `id` відомі лише з документації).

## Global Constraints

- Ключ ніколи не потрапляє в `repr`, логи й тексти помилок.
- Без `LIS_API_KEY` поведінка як зараз (жодних запитів до API, експорт для всіх стежень).
- Схема БД не змінюється (нових таблиць і колонок немає).
- Конфіг етапу 1: `LIS_API_KEY` (за замовчуванням порожньо), `LIS_API_INTERVAL` = 60 с, `LIS_API_BUDGET` = 100 запитів/хв (ліміт lis-skins — 200).
- Пріоритет джерел ціни lis-skins: кеш API (не старший за `3 × LIS_API_INTERVAL`) → `depth.site_price(name)` → `csgo.json`. Котирування з API: `Quote(price, qty=0, url)`, `url` з `csgo.json`.
- Разові назви для експорту (`📊 Глибина`) живуть 15 хв (розсувний TTL).
- Порти, домени, reverse proxy не потрібні: усі зʼєднання вихідні.
- Стиль коду й тестів як у проєкті: синхронні тести з `asyncio.run`, без pytest-asyncio; коментарі українською; тести БД — `await db.init_db(str(tmp_path / "x.db"))` і `await db.close()` у `finally`.
- Запуск тестів з кореня репозиторію: `.venv/Scripts/python.exe -m pytest -q`. База: 60 тестів зелені; після кожної задачі вони мають лишатись зеленими.
- Гілка `lis-api`; git-автор налаштований локально. Коміти закінчуються рядком `Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>`. Нічого не пушити без прохання користувача.

## Структура файлів

| Файл | Дія | Відповідальність |
|---|---|---|
| `bot/config.py` | змінити | три поля конфігу |
| `bot/lis_api.py` | створити | клієнт search API: ліміт швидкості, 429, 401, помилки, ключ прихований |
| `bot/lis_prices.py` | створити | кеш «найдешевший видимий лот» і цикл оновлення |
| `bot/market.py` | змінити | `_lis_quote` бере ціну з `LisPrices` |
| `bot/db.py` | змінити | `watched_regular_names`, `watched_qty_names` |
| `bot/depth.py` | змінити | разові назви `want` / `wanted_names` з TTL |
| `bot/poller.py` | змінити | клас `Evaluator`, `depth_names`, `refresh_depth_once`, нові сигнатури `run_*` |
| `bot/handlers.py` | змінити | `_kick_depth(depth, market)`, `depth.want` у `_depth_view` |
| `bot/__main__.py` | змінити | звʼязування компонентів |
| `bot/check_lis.py` | створити | CLI живої перевірки ключа (`python -m bot.check_lis`) |
| `tests/test_config.py`, `test_lis_api.py`, `test_lis_prices.py`, `test_market_lis.py`, `test_db_names.py`, `test_depth_want.py`, `test_depth_names.py`, `test_evaluator.py`, `test_check_lis.py` | створити | тести відповідних модулів |
| `.env.example`, `README.md`, `DEPLOY.md`, спек | змінити | документація й уточнення спеку |

---

### Task 1: Змінні конфігу

**Files:**
- Modify: `bot/config.py`
- Test: `tests/test_config.py` (створити)

**Interfaces:**
- Produces: `Config.lis_api_key: str` (не в `repr`), `Config.lis_api_interval: int` (≥ 1), `Config.lis_api_budget: int` (≥ 1).

- [ ] **Step 1: Написати тест, що падає**

`tests/test_config.py`:

```python
import pytest

from bot.config import Config

_LIS_VARS = ("LIS_API_KEY", "LIS_API_INTERVAL", "LIS_API_BUDGET")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_TOKEN", "123456:test")
    for k in _LIS_VARS:
        monkeypatch.delenv(k, raising=False)


def test_lis_api_defaults_mean_disabled():
    cfg = Config.load()
    assert cfg.lis_api_key == ""
    assert (cfg.lis_api_interval, cfg.lis_api_budget) == (60, 100)


def test_lis_api_settings_are_loaded(monkeypatch):
    monkeypatch.setenv("LIS_API_KEY", " k-123 ")
    monkeypatch.setenv("LIS_API_INTERVAL", "30")
    monkeypatch.setenv("LIS_API_BUDGET", "50")
    cfg = Config.load()
    assert cfg.lis_api_key == "k-123"          # пробіли обрізаються
    assert (cfg.lis_api_interval, cfg.lis_api_budget) == (30, 50)


def test_lis_api_numbers_have_lower_bound(monkeypatch):
    monkeypatch.setenv("LIS_API_INTERVAL", "0")
    monkeypatch.setenv("LIS_API_BUDGET", "-5")
    cfg = Config.load()
    assert (cfg.lis_api_interval, cfg.lis_api_budget) == (1, 1)


def test_lis_api_key_is_not_in_repr(monkeypatch):
    monkeypatch.setenv("LIS_API_KEY", "super-secret-key")
    assert "super-secret-key" not in repr(Config.load())
```

- [ ] **Step 2: Запустити й переконатись, що падає**

Run: `.venv/Scripts/python.exe -m pytest tests/test_config.py -q`
Expected: 4 FAILED (`AttributeError: 'Config' object has no attribute 'lis_api_key'`).

- [ ] **Step 3: Мінімальна реалізація**

У `bot/config.py` змінити імпорт:

```python
from dataclasses import dataclass, field
```

Додати поля в кінець `Config` (після `steam_enabled: bool = True`):

```python
    lis_api_key: str = field(default="", repr=False)   # ключ не має потрапляти в repr/логи
    lis_api_interval: int = 60
    lis_api_budget: int = 100
```

У `Config.load()` додати аргументи в кінець `cls(...)` (після `steam_enabled=...`):

```python
            lis_api_key=os.environ.get("LIS_API_KEY", "").strip(),
            lis_api_interval=max(1, int(os.environ.get("LIS_API_INTERVAL", "60"))),
            lis_api_budget=max(1, int(os.environ.get("LIS_API_BUDGET", "100"))),
```

- [ ] **Step 4: Переконатись, що проходить**

Run: `.venv/Scripts/python.exe -m pytest -q`
Expected: `64 passed`.

- [ ] **Step 5: Коміт**

```bash
git add bot/config.py tests/test_config.py
git commit -m "feat(config): змінні LIS_API_KEY, LIS_API_INTERVAL, LIS_API_BUDGET

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: Клієнт search API (`LisApi`)

**Files:**
- Create: `bot/lis_api.py`
- Test: `tests/test_lis_api.py` (створити)

**Interfaces:**
- Produces:
  - `class LisApiError(Exception)`
  - `@dataclass(frozen=True) class Lot: id: int; price: float`
  - `@dataclass(frozen=True) class SearchResult: lots: tuple; wire_bytes: int; body_bytes: int; elapsed_ms: int`
  - `class LisApi(key, *, base_url=DEFAULT_BASE_URL, timeout=30.0, budget_per_min=100, backoff_base=5.0)` з
    `async search(name) -> SearchResult`, `async cheapest(name) -> Lot | None`, `async aclose()`, атрибут `disabled: bool`.
  - Виняток `LisApiError` для будь-якої невдачі (мережа, 5xx, 401/403, 429 без просвітку, дивна відповідь).

- [ ] **Step 1: Написати тести, що падають**

`tests/test_lis_api.py`:

```python
import asyncio
import logging
import time

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer

from bot.lis_api import LisApi, LisApiError, Lot

KEY = "secret-key-123"


def _page(*prices):
    return {"data": [{"id": 100 + i, "name": "Kilowatt Case", "price": p}
                     for i, p in enumerate(prices)],
            "meta": {"per_page": 200, "next_cursor": None}}


class Fake:
    """Локальний двійник search API: записує запити, віддає заготовлені відповіді."""

    def __init__(self, *responses):
        self.responses = list(responses)      # (status, json_body, headers)
        self.requests = []

    async def handle(self, request):
        self.requests.append(request)
        status, body, headers = (self.responses.pop(0) if len(self.responses) > 1
                                 else self.responses[0])
        return web.json_response(body, status=status, headers=headers or {})


def _run(fake, scenario, **kw):
    kw.setdefault("budget_per_min", 60000)
    kw.setdefault("backoff_base", 0.0)

    async def go():
        app = web.Application()
        app.router.add_get("/v1/market/search", fake.handle)
        async with TestServer(app) as srv:
            api = LisApi(KEY, base_url=str(srv.make_url("/v1")), **kw)
            try:
                return await scenario(api)
            finally:
                await api.aclose()

    return asyncio.run(go())


def test_cheapest_returns_first_lot_and_sends_expected_request():
    fake = Fake((200, _page(0.13, 0.14, 0.20), None))
    lot = _run(fake, lambda api: api.cheapest("Kilowatt Case"))
    assert lot == Lot(id=100, price=0.13)
    req = fake.requests[0]
    assert req.headers["Authorization"] == f"Bearer {KEY}"
    assert req.query.getall("names[]") == ["Kilowatt Case"]
    assert req.query["game"] == "csgo" and req.query["sort_by"] == "lowest_price"


def test_cheapest_is_none_when_there_are_no_lots():
    fake = Fake((200, _page(), None))
    assert _run(fake, lambda api: api.cheapest("Kilowatt Case")) is None


def test_search_reports_page_stats():
    fake = Fake((200, _page(0.13, 0.14), None))
    res = _run(fake, lambda api: api.search("Kilowatt Case"))
    assert res.lots == (Lot(100, 0.13), Lot(101, 0.14))
    assert res.wire_bytes > 0 and res.body_bytes > 0 and res.elapsed_ms >= 0


def test_429_is_retried_after_retry_after():
    fake = Fake((429, {"message": "Too Many Attempts."}, {"retry-after": "0"}),
                (200, _page(0.13), None))
    lot = _run(fake, lambda api: api.cheapest("X"))
    assert lot == Lot(100, 0.13)
    assert len(fake.requests) == 2


def test_429_that_never_ends_raises_after_three_attempts():
    fake = Fake((429, {"message": "Too Many Attempts."}, {"retry-after": "0"}))

    async def scenario(api):
        with pytest.raises(LisApiError):
            await api.cheapest("X")

    _run(fake, scenario)
    assert len(fake.requests) == 3


def test_unauthorized_disables_client_and_stops_requests():
    fake = Fake((401, {"message": "Unauthenticated."}, None))

    async def scenario(api):
        with pytest.raises(LisApiError):
            await api.cheapest("X")
        assert api.disabled
        with pytest.raises(LisApiError):
            await api.cheapest("X")

    _run(fake, scenario)
    assert len(fake.requests) == 1          # другого запиту до сервера вже нема


def test_server_error_raises_and_backs_off_before_next_request():
    fake = Fake((500, {}, None), (200, _page(0.13), None))

    async def scenario(api):
        with pytest.raises(LisApiError):
            await api.cheapest("X")
        t0 = time.monotonic()
        lot = await api.cheapest("X")
        return lot, time.monotonic() - t0

    lot, waited = _run(fake, scenario, backoff_base=0.2)
    assert lot == Lot(100, 0.13)
    assert waited >= 0.15


def test_unexpected_response_shape_raises():
    fake = Fake((200, {"oops": 1}, None))

    async def scenario(api):
        with pytest.raises(LisApiError):
            await api.cheapest("X")

    _run(fake, scenario)


def test_network_error_becomes_lis_api_error_without_leaking_key():
    async def go():
        api = LisApi(KEY, base_url="http://127.0.0.1:1/v1", budget_per_min=60000,
                     backoff_base=0.0)
        try:
            with pytest.raises(LisApiError) as ei:
                await api.cheapest("X")
            return str(ei.value)
        finally:
            await api.aclose()

    assert KEY not in asyncio.run(go())


def test_key_never_appears_in_repr_or_logs(caplog):
    caplog.set_level(logging.DEBUG)
    fake = Fake((500, {}, None), (401, {"message": "Unauthenticated."}, None))

    async def scenario(api):
        assert KEY not in repr(api)
        for _ in range(2):
            with pytest.raises(LisApiError):
                await api.cheapest("X")

    _run(fake, scenario)
    assert KEY not in caplog.text


def test_requests_are_spaced_by_budget():
    fake = Fake((200, _page(0.13), None))

    async def scenario(api):
        t0 = time.monotonic()
        for _ in range(3):
            await api.cheapest("X")
        return time.monotonic() - t0

    elapsed = _run(fake, scenario, budget_per_min=600)      # 0.1 с між запитами
    assert elapsed >= 0.18
```

- [ ] **Step 2: Запустити й переконатись, що падає**

Run: `.venv/Scripts/python.exe -m pytest tests/test_lis_api.py -q`
Expected: помилка збору `ModuleNotFoundError: No module named 'bot.lis_api'`.

- [ ] **Step 3: Мінімальна реалізація**

`bot/lis_api.py`:

```python
"""Клієнт публічного API lis-skins (потрібен API-ключ).

Використовується лише для `GET /market/search`: найдешевший видимий лот за назвою.
Ключ ніколи не потрапляє в repr, логи та тексти помилок.
"""
from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass

import httpx

log = logging.getLogger("lis_api")

DEFAULT_BASE_URL = "https://api.lis-skins.com/v1"
_DEFAULT_RETRY_AFTER = 30.0
_MAX_429_ATTEMPTS = 3
_MAX_BACKOFF = 300.0


class LisApiError(Exception):
    """Відповідь API отримати не вдалося. Текст — без ключа."""


@dataclass(frozen=True)
class Lot:
    id: int
    price: float


@dataclass(frozen=True)
class SearchResult:
    lots: tuple           # tuple[Lot, ...] у порядку відповіді (за зростанням ціни)
    wire_bytes: int       # скільки реально прийшло по мережі (стиснуте)
    body_bytes: int       # розмір тіла після розпакування
    elapsed_ms: int


def _retry_after(resp) -> float:
    try:
        return max(0.0, float(resp.headers.get("retry-after", "")))
    except ValueError:
        return _DEFAULT_RETRY_AFTER


class LisApi:
    def __init__(self, key: str, *, base_url: str = DEFAULT_BASE_URL, timeout: float = 30.0,
                 budget_per_min: int = 100, backoff_base: float = 5.0):
        self._base = base_url.rstrip("/")
        self._gap = 60.0 / max(1, budget_per_min)
        self._backoff_base = backoff_base
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=10.0, read=timeout, write=10.0, pool=5.0),
            headers={"User-Agent": "lis-price-bot/1.0", "Accept": "application/json",
                     "Authorization": f"Bearer {key}"},
        )
        self._lock = asyncio.Lock()
        self._last_req = 0.0
        self._pause_until = 0.0
        self._fails = 0
        self.disabled = False       # 401/403: ключ недійсний, більше не пробуємо

    def __repr__(self) -> str:
        return "LisApi(key=***)"

    async def search(self, name: str) -> SearchResult:
        params = {"game": "csgo", "names[]": name, "sort_by": "lowest_price"}
        body, wire, size, ms = await self._get("/market/search", params)
        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(data, list):
            raise LisApiError("bad response shape")
        lots = []
        for it in data:
            try:
                lots.append(Lot(int(it["id"]), float(it["price"])))
            except (KeyError, TypeError, ValueError):
                raise LisApiError("bad lot in response") from None
        return SearchResult(tuple(lots), wire, size, ms)

    async def cheapest(self, name: str) -> Lot | None:
        res = await self.search(name)
        return res.lots[0] if res.lots else None

    async def aclose(self) -> None:
        await self._http.aclose()

    # ---- транспорт ----

    async def _wait_turn(self) -> None:
        now = time.monotonic()
        wait = max(self._last_req + self._gap - now, self._pause_until - now)
        if wait > 0:
            await asyncio.sleep(wait)

    def _fail(self, msg: str) -> None:
        # шумимо в лог лише перші кілька разів, далі тихо бекофимось
        (log.warning if self._fails < 3 else log.debug)("lis api %s", msg)
        self._fails += 1
        self._pause_until = time.monotonic() + min(
            self._backoff_base * 2 ** (self._fails - 1), _MAX_BACKOFF)

    async def _get(self, path: str, params: dict):
        if self.disabled:
            raise LisApiError("api disabled (invalid key)")
        async with self._lock:
            for _ in range(_MAX_429_ATTEMPTS):
                await self._wait_turn()
                t0 = time.monotonic()
                try:
                    resp = await self._http.get(self._base + path, params=params)
                except httpx.HTTPError as e:
                    self._last_req = time.monotonic()
                    self._fail(f"network error: {type(e).__name__}")
                    raise LisApiError("network error") from None
                self._last_req = time.monotonic()
                if resp.status_code == 429:
                    self._pause_until = time.monotonic() + _retry_after(resp)
                    continue
                if resp.status_code in (401, 403):
                    self.disabled = True
                    log.error("LIS_API_KEY недійсний або без доступу (HTTP %s) — API вимкнено",
                              resp.status_code)
                    raise LisApiError(f"http {resp.status_code}")
                if resp.status_code != 200:
                    self._fail(f"status {resp.status_code}")
                    raise LisApiError(f"http {resp.status_code}")
                try:
                    body = resp.json()
                except ValueError:
                    self._fail("bad json")
                    raise LisApiError("bad json") from None
                self._fails = 0
                return (body, resp.num_bytes_downloaded, len(resp.content),
                        int((time.monotonic() - t0) * 1000))
            log.warning("lis api: 429 не минає після %d спроб", _MAX_429_ATTEMPTS)
            raise LisApiError("rate limited")
```

- [ ] **Step 4: Переконатись, що проходить**

Run: `.venv/Scripts/python.exe -m pytest tests/test_lis_api.py -q`
Expected: `11 passed`.
Потім повний набір: `.venv/Scripts/python.exe -m pytest -q` → `75 passed`.

- [ ] **Step 5: Коміт**

```bash
git add bot/lis_api.py tests/test_lis_api.py
git commit -m "feat: клієнт search API lis-skins (ліміт швидкості, 429, 401, ключ прихований)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: Кеш цін `LisPrices`

**Files:**
- Create: `bot/lis_prices.py`
- Test: `tests/test_lis_prices.py` (створити)

**Interfaces:**
- Consumes: `LisApi.cheapest(name) -> Lot | None` (raises `LisApiError`), `LisApi.disabled`.
- Produces: `class LisPrices(api, interval, *, clock=time.time)` з
  `active: bool` (property), `get(name) -> float | None` (лише свіжа ціна),
  `async refresh_name(name) -> bool` (True — ціна змінилась), 
  `async run_cycle(names, on_changed=None)`, `async run(names_provider, on_changed=None)`.
  `on_changed` — `async def (name: str) -> None`; `names_provider` — `async def () -> Iterable[str]`.

- [ ] **Step 1: Написати тести, що падають**

`tests/test_lis_prices.py`:

```python
import asyncio

import pytest

from bot.lis_api import LisApiError, Lot
from bot.lis_prices import LisPrices


class FakeApi:
    """Віддає заготовлені значення по черзі: float | None | Exception."""

    def __init__(self, *script):
        self.script = list(script)
        self.calls = []
        self.disabled = False

    async def cheapest(self, name):
        self.calls.append(name)
        v = self.script.pop(0)
        if isinstance(v, Exception):
            raise v
        return None if v is None else Lot(1, v)


def test_refresh_stores_price_and_reports_changes():
    api = FakeApi(0.13, 0.13, 0.15)
    prices = LisPrices(api, 60)

    async def go():
        return [await prices.refresh_name("A"), await prices.refresh_name("A"),
                await prices.refresh_name("A")]

    assert asyncio.run(go()) == [True, False, True]     # зʼявилась, та сама, змінилась
    assert prices.get("A") == 0.15


def test_no_lots_clears_the_price():
    api = FakeApi(0.13, None)
    prices = LisPrices(api, 60)

    async def go():
        await prices.refresh_name("A")
        return await prices.refresh_name("A")

    assert asyncio.run(go()) is True
    assert prices.get("A") is None


def test_api_error_keeps_old_price():
    api = FakeApi(0.13, LisApiError("boom"))
    prices = LisPrices(api, 60)

    async def go():
        await prices.refresh_name("A")
        return await prices.refresh_name("A")

    assert asyncio.run(go()) is False
    assert prices.get("A") == 0.13


def test_price_goes_stale_after_three_intervals():
    clock = [1000.0]
    api = FakeApi(0.13)
    prices = LisPrices(api, 60, clock=lambda: clock[0])
    asyncio.run(prices.refresh_name("A"))
    clock[0] = 1000.0 + 179
    assert prices.get("A") == 0.13
    clock[0] = 1000.0 + 181
    assert prices.get("A") is None


def test_run_cycle_notifies_only_changed_names():
    api = FakeApi(0.13, 0.20, 0.13)
    prices = LisPrices(api, 60)
    changed = []

    async def on_changed(name):
        changed.append(name)

    async def go():
        await prices.run_cycle(["A", "B"], on_changed)      # обидві нові
        await prices.run_cycle(["A"], on_changed)           # A без змін

    asyncio.run(go())
    assert changed == ["A", "B"]


def test_run_cycle_survives_failing_callback():
    api = FakeApi(0.13, 0.20)
    prices = LisPrices(api, 60)
    seen = []

    async def on_changed(name):
        seen.append(name)
        if name == "A":
            raise RuntimeError("boom")

    asyncio.run(prices.run_cycle(["A", "B"], on_changed))
    assert seen == ["A", "B"]


def test_disabled_api_makes_prices_inactive_and_cycle_a_noop():
    api = FakeApi()
    api.disabled = True
    prices = LisPrices(api, 60)
    assert prices.active is False
    asyncio.run(prices.run_cycle(["A"]))
    assert api.calls == []


def test_run_loops_and_can_be_cancelled():
    api = FakeApi(0.13, 0.14, 0.15)
    prices = LisPrices(api, 1)

    async def names():
        return ["A"]

    async def go():
        task = asyncio.create_task(prices.run(names))
        await asyncio.sleep(0.3)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    asyncio.run(go())
    assert api.calls == ["A"]           # за 0.3 с — одна ітерація (інтервал 1 с)
```

- [ ] **Step 2: Запустити й переконатись, що падає**

Run: `.venv/Scripts/python.exe -m pytest tests/test_lis_prices.py -q`
Expected: `ModuleNotFoundError: No module named 'bot.lis_prices'`.

- [ ] **Step 3: Мінімальна реалізація**

`bot/lis_prices.py`:

```python
"""Кеш «найдешевший видимий лот» за назвою (з search API) і цикл його оновлення."""
from __future__ import annotations

import asyncio
import logging
import time

from .lis_api import LisApiError

log = logging.getLogger("lis_prices")

_STALE_FACTOR = 3       # запис старший за 3 інтервали вважається протухлим


class LisPrices:
    def __init__(self, api, interval: float, *, clock=time.time):
        self._api = api
        self._interval = max(1.0, float(interval))
        self._clock = clock
        self._cache: dict[str, tuple[float, float]] = {}    # name -> (price, ts)

    @property
    def active(self) -> bool:
        """False, якщо ключ недійсний: тоді бот працює на експорті, як без ключа."""
        return not self._api.disabled

    def get(self, name: str):
        """Свіжа ціна або None (нема запису / протухла)."""
        hit = self._cache.get(name)
        if hit is None:
            return None
        price, ts = hit
        if self._clock() - ts > _STALE_FACTOR * self._interval:
            return None
        return price

    async def refresh_name(self, name: str) -> bool:
        """Оновити ціну назви. True — ціна змінилась (зʼявилась, зникла, інша)."""
        try:
            lot = await self._api.cheapest(name)
        except LisApiError:
            return False                # кеш лишається й сам постаріє
        old = self._cache.get(name)
        if lot is None:
            self._cache.pop(name, None)
            return old is not None
        self._cache[name] = (lot.price, self._clock())
        return old is None or old[0] != lot.price

    async def run_cycle(self, names, on_changed=None) -> None:
        for name in names:
            if not self.active:
                return
            if await self.refresh_name(name) and on_changed is not None:
                try:
                    await on_changed(name)
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("on_changed failed for %s", name)

    async def run(self, names_provider, on_changed=None) -> None:
        """Нескінченний цикл: раз на interval (з урахуванням тривалості проходу)."""
        while self.active:
            t0 = time.monotonic()
            try:
                await self.run_cycle(await names_provider(), on_changed)
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("lis prices cycle error")
            await asyncio.sleep(max(1.0, self._interval - (time.monotonic() - t0)))
```

- [ ] **Step 4: Переконатись, що проходить**

Run: `.venv/Scripts/python.exe -m pytest tests/test_lis_prices.py -q` → `8 passed`.
Повний набір: `.venv/Scripts/python.exe -m pytest -q` → `83 passed`.

- [ ] **Step 5: Коміт**

```bash
git add bot/lis_prices.py tests/test_lis_prices.py
git commit -m "feat: кеш цін LisPrices і цикл оновлення (з протуханням і fallback-ознакою)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: `Market` бере ціну з `LisPrices`

**Files:**
- Modify: `bot/market.py:16-22` (конструктор) та `bot/market.py:44-52` (`_lis_quote`)
- Test: `tests/test_market_lis.py` (створити)

**Interfaces:**
- Consumes: `LisPrices.get(name) -> float | None` (Task 3).
- Produces: `Market(client, depth, ext_sources, steam=None, lis_prices=None)`, властивість `Market.lis_prices` (може бути `None`), нова логіка `_lis_quote`.

- [ ] **Step 1: Написати тести, що падають**

`tests/test_market_lis.py`:

```python
import types

from bot.lis import Item
from bot.market import Market
from bot.sources import Quote

NAME = "Kilowatt Case"
URL = "https://lis-skins.com/x"


class _Prices:
    def __init__(self, price):
        self.price = price

    def get(self, name):
        return self.price


def _market(*, lis_price=None, site_price=None, csgo_price=None, with_prices=True):
    item = (Item(NAME, csgo_price, csgo_price, URL, 7) if csgo_price is not None else None)
    client = types.SimpleNamespace(lookup=lambda n: item)
    depth = types.SimpleNamespace(site_price=lambda n: site_price, count=lambda n: 500)
    prices = _Prices(lis_price) if with_prices else None
    return Market(client, depth, [], lis_prices=prices)


def test_api_price_wins_over_export_and_csgo_json():
    m = _market(lis_price=0.13, site_price=0.14, csgo_price=0.12)
    assert m.quotes(NAME) == [("lis", "lis-skins", Quote(0.13, 0, URL))]
    assert m.best(NAME)[2].price == 0.13


def test_falls_back_to_export_when_api_has_no_fresh_price():
    m = _market(lis_price=None, site_price=0.14, csgo_price=0.12)
    assert m.quotes(NAME) == [("lis", "lis-skins", Quote(0.14, 500, URL))]


def test_falls_back_to_csgo_json_when_export_has_nothing():
    m = _market(lis_price=None, site_price=None, csgo_price=0.12)
    assert m.quotes(NAME) == [("lis", "lis-skins", Quote(0.12, 7, URL))]


def test_without_lis_prices_behaviour_is_unchanged():
    m = _market(site_price=0.14, csgo_price=0.12, with_prices=False)
    assert m.lis_prices is None
    assert m.quotes(NAME) == [("lis", "lis-skins", Quote(0.14, 500, URL))]


def test_api_price_without_csgo_item_has_empty_url():
    m = _market(lis_price=0.13)
    assert m.quotes(NAME) == [("lis", "lis-skins", Quote(0.13, 0, ""))]


def test_no_price_anywhere_gives_no_quote():
    assert _market().quotes(NAME) == []
```

- [ ] **Step 2: Запустити й переконатись, що падає**

Run: `.venv/Scripts/python.exe -m pytest tests/test_market_lis.py -q`
Expected: FAILED (`TypeError: Market.__init__() got an unexpected keyword argument 'lis_prices'`).

- [ ] **Step 3: Мінімальна реалізація**

У `bot/market.py` замінити конструктор:

```python
    def __init__(self, client, depth, ext_sources, steam=None, lis_prices=None):
        self._client = client
        self._depth = depth
        self._ext = list(ext_sources)
        self.steam = steam
        self._lis_prices = lis_prices
```

Додати після властивості `sources` (перед `refresh`):

```python
    @property
    def lis_prices(self):
        return self._lis_prices
```

Замінити `_lis_quote`:

```python
    def _lis_quote(self, name: str):
        item = self._client.lookup(name)
        url = item.url if item is not None else ""
        # 1) свіжа ціна з search API (кількість невідома → qty=0)
        if self._lis_prices is not None:
            p = self._lis_prices.get(name)
            if p is not None:
                return Quote(p, 0, url)
        # 2) експорт з глибиною, 3) короткий csgo.json — як було раніше
        sp = self._depth.site_price(name)
        if sp is not None:
            return Quote(sp, self._depth.count(name) or 0, url)
        if item is not None:
            return Quote(item.price, item.count, url)
        return None
```

- [ ] **Step 4: Переконатись, що проходить**

Run: `.venv/Scripts/python.exe -m pytest tests/test_market_lis.py -q` → `6 passed`.
Повний набір: `.venv/Scripts/python.exe -m pytest -q` → `89 passed`.

- [ ] **Step 5: Коміт**

```bash
git add bot/market.py tests/test_market_lis.py
git commit -m "feat(market): ціна lis-skins з API першим пріоритетом, fallback на експорт і csgo.json

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 5: Експорт лише для оптових стежень і разових запитів

**Files:**
- Modify: `bot/db.py` (після `watched_names`, приблизно рядок 222)
- Modify: `bot/depth.py` (імпорти, `__init__`, нові методи)
- Modify: `bot/poller.py` (`run_depth_refresher`, нові `depth_names`, `refresh_depth_once`)
- Modify: `bot/handlers.py` (імпорт, `_kick_depth`, `_depth_view`, три виклики `_kick_depth`)
- Test: `tests/test_db_names.py`, `tests/test_depth_want.py`, `tests/test_depth_names.py` (створити)

**Interfaces:**
- Consumes: `LisPrices.active` (Task 3), `Market.lis_prices` (Task 4).
- Produces:
  - `db.watched_regular_names() -> set[str]` (стеження з `min_qty <= 1`), `db.watched_qty_names() -> set[str]` (`min_qty > 1`).
  - `DepthIndex.want(name, *, now=None)`, `DepthIndex.wanted_names(*, now=None) -> set[str]` (TTL 15 хв, розсувний).
  - `poller.depth_names(depth, lis_prices) -> set[str]`, `poller.refresh_depth_once(depth, lis_prices=None)`.
  - `poller.run_depth_refresher(depth, cfg, lis_prices=None)`.
  - `handlers._kick_depth(depth, market)`.

- [ ] **Step 1: Написати тести, що падають**

`tests/test_db_names.py`:

```python
import asyncio

from bot import db


def test_watched_names_split_by_min_qty(tmp_path):
    async def go():
        await db.init_db(str(tmp_path / "n.db"))
        try:
            await db.add_watch(1, 10, "Regular Case", 0.13)
            await db.add_watch(1, 10, "Bulk Case", 0.13, min_qty=200)
            await db.add_watch(2, 20, "Both Case", 0.13)
            await db.add_watch(2, 20, "Both Case", 0.20, min_qty=50)
            return (await db.watched_regular_names(), await db.watched_qty_names(),
                    await db.watched_names())
        finally:
            await db.close()

    regular, qty, everything = asyncio.run(go())
    assert regular == {"Regular Case", "Both Case"}
    assert qty == {"Bulk Case", "Both Case"}
    assert everything == regular | qty
```

`tests/test_depth_want.py`:

```python
import types

from bot.depth import DepthIndex


def _idx() -> DepthIndex:
    return DepthIndex(types.SimpleNamespace(full_export_url="http://x", http_timeout=30.0))


def test_wanted_name_expires_after_ttl():
    d = _idx()
    d.want("A", now=1000)
    assert d.wanted_names(now=1000 + 899) == {"A"}
    assert d.wanted_names(now=1000 + 901) == set()


def test_want_again_extends_the_ttl():
    d = _idx()
    d.want("A", now=1000)
    d.want("A", now=1800)
    assert d.wanted_names(now=1800 + 899) == {"A"}


def test_several_names_expire_independently():
    d = _idx()
    d.want("A", now=1000)
    d.want("B", now=1500)
    assert d.wanted_names(now=1000 + 901) == {"B"}
```

`tests/test_depth_names.py`:

```python
import asyncio
import types

from bot import db, handlers, poller


class _Depth:
    """Двійник DepthIndex: пише, з якими назвами викликали refresh."""

    def __init__(self, wanted=()):
        self.wanted = list(wanted)
        self.refreshed = []

    def wanted_names(self):
        return set(self.wanted)

    def want(self, name):
        self.wanted.append(name)

    def has(self, name):
        return False

    async def refresh(self, names):
        self.refreshed.append(set(names))
        return True


async def _seed():
    await db.add_watch(1, 10, "Regular Case", 0.13)
    await db.add_watch(1, 10, "Bulk Case", 0.13, min_qty=200)


def _run(tmp_path, scenario):
    async def go():
        await db.init_db(str(tmp_path / "d.db"))
        try:
            await _seed()
            return await scenario()
        finally:
            await db.close()

    return asyncio.run(go())


def test_depth_names_with_active_api_are_bulk_plus_adhoc(tmp_path):
    prices = types.SimpleNamespace(active=True)
    names = _run(tmp_path, lambda: poller.depth_names(_Depth(["Adhoc Case"]), prices))
    assert names == {"Bulk Case", "Adhoc Case"}


def test_depth_names_without_api_are_all_watched(tmp_path):
    names = _run(tmp_path, lambda: poller.depth_names(_Depth(["Adhoc Case"]), None))
    assert names == {"Regular Case", "Bulk Case"}


def test_depth_names_with_disabled_api_are_all_watched(tmp_path):
    prices = types.SimpleNamespace(active=False)
    names = _run(tmp_path, lambda: poller.depth_names(_Depth(), prices))
    assert names == {"Regular Case", "Bulk Case"}


def test_refresh_depth_once_passes_names_and_clears_when_empty(tmp_path):
    prices = types.SimpleNamespace(active=True)
    depth = _Depth()

    async def scenario():
        await poller.refresh_depth_once(depth, prices)           # є оптове стеження
        await db.remove_watch(1, 2)                              # видаляємо Bulk Case
        await poller.refresh_depth_once(depth, prices)           # пусто → очищення драбин

    _run(tmp_path, scenario)
    assert depth.refreshed == [{"Bulk Case"}, set()]


def test_kick_depth_uses_the_same_name_set(tmp_path):
    depth = _Depth(["Adhoc Case"])
    market = types.SimpleNamespace(lis_prices=types.SimpleNamespace(active=True))
    _run(tmp_path, lambda: handlers._kick_depth(depth, market))
    assert depth.refreshed == [{"Bulk Case", "Adhoc Case"}]


def test_opening_depth_of_a_regular_watch_registers_the_name(tmp_path):
    depth = _Depth()
    market = types.SimpleNamespace(lis_prices=types.SimpleNamespace(active=True))

    async def scenario():
        txt, _ = await handlers._depth_view(1, 1, None, depth, market)
        await asyncio.sleep(0.1)                # дати фоновому _kick_depth відпрацювати
        return txt

    txt = _run(tmp_path, scenario)
    assert "вантажиться" in txt
    assert depth.wanted == ["Regular Case"]
    assert depth.refreshed == [{"Bulk Case", "Regular Case"}]
```

- [ ] **Step 2: Запустити й переконатись, що падає**

Run: `.venv/Scripts/python.exe -m pytest tests/test_db_names.py tests/test_depth_want.py tests/test_depth_names.py -q`
Expected: FAILED / errors (`AttributeError: module 'bot.db' has no attribute 'watched_regular_names'`, `'DepthIndex' object has no attribute 'want'`, `module 'bot.poller' has no attribute 'depth_names'`).

- [ ] **Step 3: Реалізація**

`bot/db.py` — після функції `watched_names`:

```python
async def watched_regular_names() -> set:
    """Назви звичайних стежень (min_qty = 1): їхню ціну тягнемо з search API."""
    cur = await _db.execute("SELECT DISTINCT skin_name FROM watches WHERE min_qty <= 1")
    return {r["skin_name"] for r in await cur.fetchall()}


async def watched_qty_names() -> set:
    """Назви оптових стежень (min_qty > 1): лише їм потрібен великий експорт з глибиною."""
    cur = await _db.execute("SELECT DISTINCT skin_name FROM watches WHERE min_qty > 1")
    return {r["skin_name"] for r in await cur.fetchall()}
```

`bot/depth.py` — додати константу після `_FRESH_S = 120`:

```python
# разові назви (кнопка «📊 Глибина» у звичайного стеження) тримаємо в індексі 15 хв
_WANT_TTL = 15 * 60
```

У `DepthIndex.__init__` додати рядок після `self._lock`:

```python
        self._wanted: dict[str, float] = {}   # name -> час, коли перестаємо тягнути
```

Додати методи після `refresh` (перед `_do_refresh`):

```python
    def want(self, name: str, *, now: float | None = None) -> None:
        """Попросити завантажити глибину назви на _WANT_TTL (повторний виклик подовжує)."""
        self._wanted[name] = (time.time() if now is None else now) + _WANT_TTL

    def wanted_names(self, *, now: float | None = None) -> set:
        t = time.time() if now is None else now
        self._wanted = {n: exp for n, exp in self._wanted.items() if exp > t}
        return set(self._wanted)
```

`bot/poller.py` — замінити `run_depth_refresher` і додати дві функції перед ним:

```python
async def depth_names(depth, lis_prices) -> set:
    """Назви для великого експорту.

    З активним API: оптові стеження ∪ разові (📊 Глибина).
    Без ключа / з недійсним ключем — усі стеження, як було до API."""
    if lis_prices is None or not lis_prices.active:
        return await db.watched_names()
    return await db.watched_qty_names() | depth.wanted_names()


async def refresh_depth_once(depth, lis_prices=None) -> None:
    # порожній набір теж передаємо: depth.refresh очищає старі драбини без скачування
    await depth.refresh(await depth_names(depth, lis_prices))


async def run_depth_refresher(depth, cfg, lis_prices=None):
    while True:
        try:
            await refresh_depth_once(depth, lis_prices)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("depth refresh cycle error")
        await asyncio.sleep(max(60, cfg.depth_refresh_min * 60))
```

`bot/handlers.py`:
- у рядку імпорту `from . import alerts, db, history, keyboards, matcher` додати `poller`:

```python
from . import alerts, db, history, keyboards, matcher, poller
```

- замінити `_kick_depth`:

```python
async def _kick_depth(depth, market):
    try:
        await poller.refresh_depth_once(depth, market.lis_prices)
    except Exception:
        log.exception("ad-hoc depth refresh failed")
```

- у трьох місцях замінити `asyncio.create_task(_kick_depth(depth))` на `asyncio.create_task(_kick_depth(depth, market))` (функції `_depth_view`, `_add_watch` — дві точки).
- у `_depth_view` одразу після `name = w["skin_name"]` додати `depth.want(name)`:

```python
    name = w["skin_name"]
    depth.want(name)      # разова назва: експорт дотягне глибину й тримає її 15 хв
    if not depth.has(name):
        asyncio.create_task(_kick_depth(depth, market))
```

(перший рядок `if not depth.has(name):` і `create_task` уже існують — потрібно лише змінити аргументи `_kick_depth` і вставити `depth.want(name)`).

- [ ] **Step 4: Переконатись, що проходить**

Run: `.venv/Scripts/python.exe -m pytest tests/test_db_names.py tests/test_depth_want.py tests/test_depth_names.py -q` → `10 passed`.
Повний набір: `.venv/Scripts/python.exe -m pytest -q` → `99 passed`.
Перевірити, що не лишилось старих викликів: `grep -n "_kick_depth(depth)" bot/handlers.py` → порожньо.

- [ ] **Step 5: Коміт**

```bash
git add bot/db.py bot/depth.py bot/poller.py bot/handlers.py tests/test_db_names.py tests/test_depth_want.py tests/test_depth_names.py
git commit -m "feat: великий експорт лише для оптових стежень і разових запитів глибини

З активним API експорт тягнеться для x<шт>-стежень і назв, для яких хтось
відкрив «📊 Глибина» (TTL 15 хв). Без ключа — усі стеження, як раніше.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 6: `Evaluator` — оцінка стежень з одним `Lock`

**Files:**
- Modify: `bot/poller.py` (замінити `_cycle` і `run_poller` класом `Evaluator`)
- Test: `tests/test_evaluator.py` (створити)

**Interfaces:**
- Consumes: `db.all_watches()`, `db.mark_triggered`, `db.set_last_price`, `db.record_prices`, `alerts.evaluate`, наявні `_price_alert`, `_qty_alert`; `market.best/quotes/case_names`, `depth.buyable_qty/site_price/fill_price`.
- Produces:
  - `class Evaluator(bot, depth, market)` з `async run_cycle()` (усі стеження + історія цін + розсилка) і `async evaluate_name(name)` (стеження однієї назви + розсилка). Обидва під одним `asyncio.Lock`; розсилка Telegram — поза замком.
  - `run_poller(evaluator, client, market, cfg)` (замість `run_poller(bot, client, depth, market, cfg)`).

- [ ] **Step 1: Написати тести, що падають**

`tests/test_evaluator.py`:

```python
import asyncio

from bot import db
from bot.poller import Evaluator
from bot.sources import Quote


class _Bot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, reply_markup=None):
        await asyncio.sleep(0)          # віддати керування: без Lock тут можлива гонка
        self.sent.append((chat_id, text))


class _Market:
    """Одна ціна на назву — цього досить для _price_alert."""

    def __init__(self, prices):
        self.prices = prices

    def best(self, name):
        p = self.prices.get(name)
        return ("lis", "lis-skins", Quote(p, 0, "u")) if p is not None else None

    def quotes(self, name):
        b = self.best(name)
        return [b] if b else []

    def case_names(self, limit=120):
        return []


class _Depth:
    """Оптових стежень у цих тестах нема."""

    def buyable_qty(self, *a):
        return None

    def site_price(self, *a):
        return None

    def fill_price(self, *a):
        return None


def _run(tmp_path, scenario):
    async def go():
        await db.init_db(str(tmp_path / "e.db"))
        try:
            return await scenario()
        finally:
            await db.close()

    return asyncio.run(go())


def test_evaluate_name_fires_once_and_only_for_that_name(tmp_path):
    async def scenario():
        await db.add_watch(1, 111, "A Case", 0.13)
        await db.add_watch(2, 222, "B Case", 0.13)
        bot = _Bot()
        ev = Evaluator(bot, _Depth(), _Market({"A Case": 0.10, "B Case": 0.10}))
        await ev.evaluate_name("A Case")
        await ev.evaluate_name("A Case")            # вдруге — тиша (triggered)
        return bot.sent, [w["triggered"] for w in await db.all_watches()]

    sent, triggered = _run(tmp_path, scenario)
    assert [chat for chat, _ in sent] == [111]
    assert triggered == [1, 0]


def test_rearm_then_fire_again(tmp_path):
    async def scenario():
        await db.add_watch(1, 111, "A Case", 0.13)
        market = _Market({"A Case": 0.10})
        bot = _Bot()
        ev = Evaluator(bot, _Depth(), market)
        await ev.evaluate_name("A Case")            # fire
        market.prices["A Case"] = 0.20
        await ev.evaluate_name("A Case")            # rearm, без повідомлення
        market.prices["A Case"] = 0.10
        await ev.evaluate_name("A Case")            # fire вдруге
        return len(bot.sent)

    assert _run(tmp_path, scenario) == 2


def test_muted_watch_gets_no_message_but_is_marked_triggered(tmp_path):
    async def scenario():
        wid, _ = await db.add_watch(1, 111, "A Case", 0.13)
        await db.set_muted(1, wid, True)
        bot = _Bot()
        ev = Evaluator(bot, _Depth(), _Market({"A Case": 0.10}))
        await ev.evaluate_name("A Case")
        return bot.sent, (await db.all_watches())[0]["triggered"]

    sent, triggered = _run(tmp_path, scenario)
    assert sent == [] and triggered == 1


def test_concurrent_evaluations_do_not_double_fire(tmp_path):
    async def scenario():
        await db.add_watch(1, 111, "A Case", 0.13)
        bot = _Bot()
        ev = Evaluator(bot, _Depth(), _Market({"A Case": 0.10}))
        await asyncio.gather(ev.evaluate_name("A Case"), ev.evaluate_name("A Case"),
                             ev.run_cycle())
        return len(bot.sent)

    assert _run(tmp_path, scenario) == 1


def test_cycle_groups_alerts_per_chat_and_records_history(tmp_path):
    async def scenario():
        await db.add_watch(1, 111, "A Case", 0.13)
        await db.add_watch(1, 111, "B Case", 0.13)
        bot = _Bot()
        ev = Evaluator(bot, _Depth(), _Market({"A Case": 0.10, "B Case": 0.11}))
        await ev.run_cycle()
        return bot.sent, await db.price_series("A Case", 24)

    sent, series = _run(tmp_path, scenario)
    assert len(sent) == 1 and "Спрацювало (2)" in sent[0][1]
    assert len(series) == 1
```

- [ ] **Step 2: Запустити й переконатись, що падає**

Run: `.venv/Scripts/python.exe -m pytest tests/test_evaluator.py -q`
Expected: `ImportError: cannot import name 'Evaluator' from 'bot.poller'`.

- [ ] **Step 3: Реалізація**

У `bot/poller.py` замінити цілу функцію `_cycle(bot, client, depth, market)` (від `async def _cycle` до кінця функції) класом:

```python
class Evaluator:
    """Оцінка стежень і розсилка алертів.

    Один Lock: повний цикл і перевірка окремої назви (після оновлення її ціни з API)
    не можуть працювати одночасно — інакше обидві прочитають triggered=0 і надішлють
    алерт двічі. Розсилка в Telegram відбувається вже поза замком."""

    def __init__(self, bot, depth, market):
        self._bot = bot
        self._depth = depth
        self._market = market
        self._lock = asyncio.Lock()

    async def run_cycle(self):
        async with self._lock:
            fired, seen = await self._evaluate(await db.all_watches())
            await self._record_history(seen)
        await self._send(fired)

    async def evaluate_name(self, name):
        async with self._lock:
            watches = [w for w in await db.all_watches() if w["skin_name"] == name]
            fired, _ = await self._evaluate(watches)
        await self._send(fired)

    async def _evaluate(self, watches):
        depth, market = self._depth, self._market
        fired: dict[int, list] = {}  # chat_id -> [(text, kb, one_liner)]
        seen: dict[str, float] = {}  # name -> best price (для історії)
        for w in watches:
            name = w["skin_name"]
            min_qty = w["min_qty"] or 1
            muted = db.is_muted(w)
            best = market.best(name)
            price = best[2].price if best else None
            if price is not None:
                seen[name] = price

            if min_qty > 1:
                qty = depth.buyable_qty(name, w["target_price"])
                if qty is None:
                    continue
                met = qty >= min_qty
                if met and not w["triggered"]:
                    if not muted:
                        fired.setdefault(w["chat_id"], []).append(
                            _qty_alert(w, name, qty, depth, market))
                    await db.mark_triggered(w["id"], price, True)
                elif not met and w["triggered"]:
                    await db.mark_triggered(w["id"], price, False)
                elif price is not None and price != w["last_price"]:
                    await db.set_last_price(w["id"], price)
                continue

            decision = alerts.evaluate(w["target_price"], bool(w["triggered"]),
                                       price, w["direction"])
            if decision == "fire":
                if not muted:
                    fired.setdefault(w["chat_id"], []).append(
                        _price_alert(w["id"], name, w["target_price"], w["direction"], market))
                await db.mark_triggered(w["id"], price, True)
            elif decision == "rearm":
                await db.mark_triggered(w["id"], price, False)
            elif price is not None and price != w["last_price"]:
                await db.set_last_price(w["id"], price)
        return fired, seen

    async def _record_history(self, seen):
        # історія цін: стеження + універсум кейсів (для «топ · рух за 7д»)
        market = self._market
        try:
            for n in market.case_names(120):
                if n not in seen:
                    b = market.best(n)
                    if b is not None:
                        seen[n] = b[2].price
        except Exception:
            log.exception("case universe snapshot failed")
        if seen:
            try:
                await db.record_prices(seen.items())
            except Exception:
                log.exception("record_prices failed")

    async def _send(self, fired):
        for chat_id, items in fired.items():
            if len(items) == 1:
                txt, kb, _ = items[0]
            else:
                body = "\n".join(f"▎{one}" for _, _, one in items)
                txt, kb = f"🔔 <b>Спрацювало ({len(items)})</b>\n{body}", None
            try:
                await self._bot.send_message(chat_id, txt, reply_markup=kb)
            except Exception:
                log.exception("alert send failed for chat %s", chat_id)
            await asyncio.sleep(0.05)
```

Замінити `run_poller`:

```python
async def run_poller(evaluator, client, market, cfg):
    while True:
        try:
            await client.refresh()
            await market.refresh()
            if client.ready():
                await evaluator.run_cycle()
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("poll cycle error")
        await asyncio.sleep(cfg.poll_interval)
```

Перевірити, що ніде більше немає `_cycle(`: `grep -rn "_cycle(" bot/ tests/` → лише `run_cycle`, `refresh_depth_once`-подібних згадок нема.

Увага: після цього кроку `bot/__main__.py` ще викликає `run_poller` зі старою сигнатурою — це виправляє Task 7. Тести Task 6 його не імпортують.

- [ ] **Step 4: Переконатись, що проходить**

Run: `.venv/Scripts/python.exe -m pytest tests/test_evaluator.py -q` → `5 passed`.
Повний набір: `.venv/Scripts/python.exe -m pytest -q` → `104 passed`.

Перевірка, що Lock справді потрібен (мутація): тимчасово замінити в `Evaluator` обидва `async with self._lock:` на `if True:`, запустити `.venv/Scripts/python.exe -m pytest tests/test_evaluator.py::test_concurrent_evaluations_do_not_double_fire -q` — очікується FAILED (`assert 2 == 1` або більше); потім повернути `async with self._lock:` і переконатись, що знову зелено.

- [ ] **Step 5: Коміт**

```bash
git add bot/poller.py tests/test_evaluator.py
git commit -m "refactor(poller): Evaluator з одним Lock і перевіркою окремої назви

_cycle перетворено на клас: run_cycle (усі стеження + історія) і evaluate_name
(одна назва). Один Lock не дає повному циклу й точковій перевірці надіслати
один алерт двічі.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 7: Звʼязування в `__main__`

**Files:**
- Modify: `bot/__main__.py`

**Interfaces:**
- Consumes: `Config.lis_api_*` (Task 1), `LisApi` (Task 2), `LisPrices` (Task 3), `Market(..., lis_prices)` (Task 4), `run_depth_refresher(depth, cfg, lis_prices)` (Task 5), `Evaluator`, `run_poller(evaluator, client, market, cfg)` (Task 6), `db.watched_regular_names` (Task 5).

Цей файл — склейка без нової логіки, тому окремого юніт-тесту нема (як і в поточного `main()`); перевіряється повним набором + наскрізним запуском нижче.

- [ ] **Step 1: Змінити імпорти**

У блоці імпортів `bot/__main__.py`:

```python
from .lis import LisClient
from .lis_api import LisApi
from .lis_prices import LisPrices
from .market import Market
from .poller import Evaluator, run_depth_refresher, run_hist_pruner, run_poller
```

(замінює рядки `from .lis import LisClient`, `from .market import Market`, `from .poller import run_depth_refresher, run_hist_pruner, run_poller`).

- [ ] **Step 2: Створення компонентів**

Замінити фрагмент від `depth = DepthIndex(cfg)` до `if ext_sources:` на:

```python
    depth = DepthIndex(cfg)
    ext_sources = build_sources(cfg)
    steam = SteamPrices(cfg.steam_enabled)
    lis_api = lis_prices = None
    if cfg.lis_api_key:
        lis_api = LisApi(cfg.lis_api_key, timeout=cfg.http_timeout,
                         budget_per_min=cfg.lis_api_budget)
        lis_prices = LisPrices(lis_api, cfg.lis_api_interval)
        log.info("lis api: увімкнено (інтервал %ss, бюджет %s запитів/хв)",
                 cfg.lis_api_interval, cfg.lis_api_budget)
    market = Market(client, depth, ext_sources, steam, lis_prices)
    if ext_sources:
```

Після створення `bot`/`dp` (після рядка `dp["market"] = market`) додати:

```python
    evaluator = Evaluator(bot, depth, market)
```

- [ ] **Step 3: Задачі й закриття**

Замінити список `tasks` і додати задачу API:

```python
    tasks = [
        asyncio.create_task(run_poller(evaluator, client, market, cfg)),
        asyncio.create_task(run_depth_refresher(depth, cfg, lis_prices)),
        asyncio.create_task(run_hist_pruner()),
    ]
    if lis_prices is not None:
        tasks.append(asyncio.create_task(
            lis_prices.run(db.watched_regular_names, evaluator.evaluate_name)))
```

У блоці `finally` перед `await db.close()` додати:

```python
        if lis_api is not None:
            await lis_api.aclose()
```

- [ ] **Step 4: Повний набір і наскрізний запуск**

Run: `.venv/Scripts/python.exe -m pytest -q` → `104 passed`.

Створити тимчасову БД зі стеженням і запустити бота з **фейковими** токеном і ключем (реального ключа тут нема й не потрібно):

```bash
SCR="C:/Users/User/AppData/Local/Temp/claude/C-------------/b7293b17-25ae-4451-be46-a1997a9acd5a/scratchpad"
rm -f "$SCR/smoke2.db"
.venv/Scripts/python.exe -c "
import asyncio
from bot import db
async def m():
    await db.init_db(r'$SCR/smoke2.db')
    await db.add_watch(1, 1, 'Kilowatt Case', 0.13)
    await db.close()
asyncio.run(m())"
TELEGRAM_TOKEN=123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA LIS_API_KEY=fake-key-123 DB_PATH="$SCR/smoke2.db" SOURCES= STEAM_ENABLED=0 timeout 60 .venv/Scripts/python.exe -m bot > "$SCR/smoke2.log" 2>&1; echo "exit=$?"
grep -E "lis api|LIS_API_KEY|catalog|Unauthorized" "$SCR/smoke2.log" | head; echo "--- ключ у логах: ---"; grep -c "fake-key-123" "$SCR/smoke2.log"
```

Expected: у логах рядок `lis api: увімкнено (інтервал 60s, бюджет 100 запитів/хв)`; далі або `LIS_API_KEY недійсний або без доступу (HTTP 401/403) — API вимкнено`, або (якщо мережа до api.lis-skins.com недоступна) попередження `lis api network error`. Через фейковий токен Telegram повертає `Unauthorized`: бот або завершується (`exit=1`), або aiogram повторює спроби з паузами й процес обривається за `timeout` (`exit=124`) — обидва варіанти нормальні. Головне: бот дійшов до запуску без винятків у нашому коді, а лічильник ключа у логах `0`.

- [ ] **Step 5: Коміт**

```bash
git add bot/__main__.py
git commit -m "feat: підключити LisApi, LisPrices і Evaluator в main

Без LIS_API_KEY нічого не змінюється; з ключем ціна lis-skins оновлюється
циклом по назвах стежень, а точкова перевірка одразу оцінює їхні стеження.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 8: CLI живої перевірки `python -m bot.check_lis`

**Files:**
- Create: `bot/check_lis.py`
- Test: `tests/test_check_lis.py` (створити)

**Interfaces:**
- Consumes: `LisApi.search(name) -> SearchResult`, `LisApi.disabled`, `SearchResult` (Task 2).
- Produces: `format_report(name, result) -> str`, `async _main(names, *, base_url=DEFAULT_BASE_URL) -> int` (код виходу), `main()`.

Навіщо: користувач на VM запускає команду й пересилає вивід (без ключа) — це «ворота етапу 1» зі спеку (розділ 8, живі перевірки 1–2).

- [ ] **Step 1: Написати тести, що падають**

`tests/test_check_lis.py`:

```python
import asyncio

from aiohttp import web
from aiohttp.test_utils import TestServer

from bot import check_lis
from bot.lis_api import Lot, SearchResult

KEY = "secret-key-123"


def test_format_report_shows_cheapest_and_page_stats():
    res = SearchResult((Lot(7, 0.13), Lot(8, 0.14)), wire_bytes=900, body_bytes=2400,
                       elapsed_ms=85)
    line = check_lis.format_report("Kilowatt Case", res)
    assert "Kilowatt Case" in line and "$0.13" in line and "#7" in line
    assert "лотів на сторінці 2" in line
    assert "900" in line and "2400" in line and "85 мс" in line
    assert "УВАГА" not in line


def test_format_report_warns_when_first_lot_is_not_the_cheapest():
    res = SearchResult((Lot(7, 0.20), Lot(8, 0.13)), 10, 20, 5)
    assert "УВАГА" in check_lis.format_report("X", res)


def test_format_report_for_empty_page():
    line = check_lis.format_report("X", SearchResult((), 10, 20, 5))
    assert "лотів нема" in line


def test_main_prints_report_and_never_the_key(monkeypatch, capsys):
    monkeypatch.setenv("LIS_API_KEY", KEY)

    async def handler(request):
        return web.json_response({"data": [{"id": 5, "name": "Kilowatt Case", "price": 0.13}],
                                  "meta": {"per_page": 200, "next_cursor": None}})

    async def go():
        app = web.Application()
        app.router.add_get("/v1/market/search", handler)
        async with TestServer(app) as srv:
            return await check_lis._main(["Kilowatt Case"],
                                         base_url=str(srv.make_url("/v1")))

    code = asyncio.run(go())
    out = capsys.readouterr().out
    assert code == 0 and "Kilowatt Case" in out and "$0.13" in out
    assert KEY not in out


def test_main_without_key_exits_with_hint(monkeypatch, capsys):
    monkeypatch.delenv("LIS_API_KEY", raising=False)
    assert asyncio.run(check_lis._main(["X"])) == 2
    assert "LIS_API_KEY" in capsys.readouterr().out
```

- [ ] **Step 2: Запустити й переконатись, що падає**

Run: `.venv/Scripts/python.exe -m pytest tests/test_check_lis.py -q`
Expected: `ImportError: cannot import name 'check_lis' from 'bot'`.

- [ ] **Step 3: Реалізація**

`bot/check_lis.py`:

```python
"""Жива перевірка API-ключа lis-skins.

    python -m bot.check_lis "Kilowatt Case" "Fever Case"

Читає LIS_API_KEY з середовища або .env, робить по одному search-запиту на назву й друкує:
найдешевший лот, скільки лотів на сторінці, розмір відповіді й час. Ключ не друкується,
тож вивід можна безпечно пересилати.
"""
from __future__ import annotations

import asyncio
import os
import sys

from . import config  # noqa: F401  — імпорт виконує load_dotenv() (підхоплює .env)
from .lis_api import DEFAULT_BASE_URL, LisApi, LisApiError, SearchResult


def format_report(name: str, res: SearchResult) -> str:
    if not res.lots:
        return f"{name}: лотів нема ({res.elapsed_ms} мс)"
    prices = [lot.price for lot in res.lots]
    first = res.lots[0]
    order = ("OK" if first.price == min(prices)
             else f"УВАГА: перший лот ${first.price} не найдешевший (мін ${min(prices)})")
    return (f"{name}: найдешевший ${first.price:.2f} (лот #{first.id}), "
            f"лотів на сторінці {len(res.lots)}, сортування {order}, "
            f"відповідь {res.wire_bytes} Б по мережі / {res.body_bytes} Б розпаковано, "
            f"{res.elapsed_ms} мс")


async def _main(names, *, base_url: str = DEFAULT_BASE_URL) -> int:
    key = os.environ.get("LIS_API_KEY", "").strip()
    if not key:
        print("LIS_API_KEY не заданий (env або .env)")
        return 2
    api = LisApi(key, base_url=base_url)
    try:
        for name in names:
            try:
                print(format_report(name, await api.search(name)))
            except LisApiError as e:
                print(f"{name}: помилка API ({e})")
                if api.disabled:
                    return 1
    finally:
        await api.aclose()
    return 0


def main() -> None:
    names = sys.argv[1:]
    if not names:
        print('Використання: python -m bot.check_lis "Kilowatt Case" ["Fever Case" ...]')
        raise SystemExit(2)
    raise SystemExit(asyncio.run(_main(names)))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Переконатись, що проходить**

Run: `.venv/Scripts/python.exe -m pytest tests/test_check_lis.py -q` → `5 passed`.
Повний набір: `.venv/Scripts/python.exe -m pytest -q` → `109 passed`.

- [ ] **Step 5: Коміт**

```bash
git add bot/check_lis.py tests/test_check_lis.py
git commit -m "feat: python -m bot.check_lis — жива перевірка ключа без показу ключа

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 9: Документація, уточнення спеку, фінальна перевірка

**Files:**
- Modify: `.env.example`, `README.md`, `DEPLOY.md`
- Modify: `docs/superpowers/specs/2026-09-21-lis-live-prices-design.md`

Документація тестів не має; перевіряється перечитуванням і повним набором.

- [ ] **Step 1: `.env.example`**

Після рядка `LIS_EXPORT_URL=https://lis-skins.com/market_export_json/csgo.json` (і порожнього рядка після нього) вставити:

```
# API-ключ lis-skins (lis-skins.com/profile/api). Порожньо = ціна lis-skins з експорту, як раніше.
LIS_API_KEY=
# Як часто оновлювати ціну через API, секунд (по черзі для кожної назви зі стежень)
LIS_API_INTERVAL=60
# Скільки запитів на хвилину дозволяємо собі (ліміт lis-skins — 200)
LIS_API_BUDGET=100

```

- [ ] **Step 2: `README.md`**

Замінити абзац (рядки 6–10):

```
Працює на безкоштовних експортах lis-skins — **API-ключ не потрібен**:

- `csgo.json` (~4 МБ, раз на 60 с) — каталог назв;
- `api_csgo_full.json` (~160 МБ gzip, раз на `DEPTH_REFRESH_MIN`) — **точна ціна**
  й глибина ринку. Тягнеться, лише коли є хоч одне стеження.
```

на:

```
Працює на безкоштовних експортах lis-skins — **API-ключ не обовʼязковий**:

- `csgo.json` (~4 МБ, раз на 60 с) — каталог назв;
- `api_csgo_full.json` (~160 МБ gzip, раз на `DEPTH_REFRESH_MIN`) — **точна ціна**
  й глибина ринку. Тягнеться, лише коли є хоч одне стеження.

**З API-ключем** (`LIS_API_KEY`, платний акаунт lis-skins) ціна звичайних стежень береться
з `GET /v1/market/search` — найдешевший лот, який **видно на сайті**, оновлюється раз на
`LIS_API_INTERVAL` секунд по кожній назві (бюджет `LIS_API_BUDGET` запитів/хв, ліміт lis-skins
— 200). Великий експорт тоді тягнеться лише для оптових стежень (`x<шт>`) і для назв, для яких
відкрили `📊 Глибина` (кеш 15 хв). Перевірити ключ: `python -m bot.check_lis "Kilowatt Case"`.
Без ключа або з недійсним ключем бот працює як раніше.
```

- [ ] **Step 3: `DEPLOY.md`**

Перед рядком `---` над заголовком `### Альтернатива без GitHub — залити папку напряму` вставити розділ:

````
## 6. Увімкнути API-ключ lis-skins (опційно)

З ключем ціна lis-skins береться з search API (свіжіша й значно легша для сервера, ніж
експорт 160 МБ). Порти й домен **не потрібні** — усі зʼєднання вихідні.

1. Забрати код гілки:

```bash
cd ~/lis-price-bot && git fetch origin && git checkout lis-api
```

2. Додати ключ у `.env`. Команда питає ключ у прихованому режимі: він не показується на екрані
   і не потрапляє в історію shell (у чат ключ не надсилайте):

```bash
read -rs -p "LIS_API_KEY: " K && printf '\nLIS_API_KEY=%s\n' "$K" >> ~/lis-price-bot/.env; unset K
```

3. Жива перевірка ключа (вивід без ключа можна надсилати розробнику):

```bash
cd ~/lis-price-bot && .venv/bin/python -m bot.check_lis "Kilowatt Case" "Fever Case"
```

   Порівняйте «найдешевший» з ціною на сторінці lis-skins для цих кейсів. Також зверніть увагу
   на розмір відповіді та час.

4. Перезапустити й перевірити логи (шукайте `lis api: увімкнено`):

```bash
sudo systemctl restart lis-price-bot
```

```bash
journalctl -u lis-price-bot -n 30 --no-pager
```

5. Відкат: прибрати ключ і перезапустити (бот повертається до експорту) або повернутись на `main`:

```bash
sed -i '/^LIS_API_KEY=/d' ~/lis-price-bot/.env && sudo systemctl restart lis-price-bot
```

````

- [ ] **Step 4: Уточнення спеку**

У `docs/superpowers/specs/2026-09-21-lis-live-prices-design.md`:

(a) у розділі 4.4 замінити

```
- Запис `set_last_price` у БД на кожну зміну ціни при частих оновленнях згладжується: пишемо, лише
  якщо ціна змінилась і з останнього запису минуло ≥ 30 с.
```

на

```
- Згладжування запису `set_last_price` переноситься в етап 2 (потік подій). На етапі 1 API-цикл і
  поллер бачать однакову ціну, тож зайвих записів у БД нема.
```

(b) у розділі 4.3 замінити `2. \`depth.site_price(name)\` (експорт), як зараз;` на

```
2. `depth.site_price(name)` (експорт; драбини є лише для назв, які завантажені: оптові та разові —
   для решти пункт пропускається);
```

(c) у розділі 8 замінити `Живі перевірки на VM (потрібен ключ користувача; результати повертаються мені без ключа):` на

```
Живі перевірки на VM (потрібен ключ користувача; для 1–2 є команда `python -m bot.check_lis "<назва>" …`; результати повертаються без ключа):
```

- [ ] **Step 5: Фінальна перевірка**

Run: `.venv/Scripts/python.exe -m pytest -q` → `109 passed`.
Run: `grep -rnE "secret-key|fake-key|LIS_API_KEY=[^ ]" bot/ .env.example README.md DEPLOY.md` → у `bot/` збігів нема; у `.env.example` лише порожній `LIS_API_KEY=`.
Run: `git status --short` → чисто після коміту; `git log --oneline -10` → 9 нових комітів поверх `0d39ae5`.

- [ ] **Step 6: Коміт**

```bash
git add .env.example README.md DEPLOY.md docs/superpowers/specs/2026-09-21-lis-live-prices-design.md
git commit -m "docs: API-ключ lis-skins (env, README, DEPLOY розділ 6), уточнення спеку

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

- [ ] **Step 7: Не пушити без прохання**

Повідомити користувачеві: код етапу 1 закомічено на гілці `lis-api`, тести зелені; запушити — за його словом. Далі — жива перевірка на VM за `DEPLOY.md` розділ 6, і лише після неї пишемо план етапу 2.

---

## Самоперевірка плану проти спеку

| Розділ спеку | Задача |
|---|---|
| 4.1 клієнт API (запит, ліміт, 429, 401/403, помилки, ключ прихований) | Task 2 |
| 4.2 `LisPrices` і цикл | Task 3, Task 7 |
| 4.3 інтеграція з `Market`, fallback, `qty=0` | Task 4 |
| 4.4 `evaluate_name`, Lock, незмінні `evaluate`/анти-спам | Task 6 (згладжування `set_last_price` перенесено в етап 2 — Task 9, крок 4a) |
| 4.5 експорт лише для оптових + разові назви (TTL 15 хв, `depth_names`) | Task 5 |
| 6 конфігурація (етап 1: три змінні) | Task 1; етап 2 змінні — в плані етапу 2 |
| 7 обробка помилок | Task 2 (429, 401/403, мережа, 5xx, форма відповіді), Task 3 (протухання кешу), Task 4 (fallback) |
| 8 тестування, живі перевірки 1–2 | тести в кожній задачі; `check_lis` — Task 8; інструкція — Task 9 |
| 9 розгортання і відкат | Task 9 (DEPLOY.md) |
| 5 (етап 2: WebSocket) | **поза цим планом** — окремий план після живої перевірки |
| Свідомо не входить (розділ 2) | не реалізується |

Типи й імена узгоджені між задачами: `LisApi.cheapest/search/disabled/aclose`, `Lot(id, price)`, `SearchResult(lots, wire_bytes, body_bytes, elapsed_ms)`, `LisPrices.get/refresh_name/run_cycle/run/active`, `Market(..., lis_prices)` + `Market.lis_prices`, `db.watched_regular_names/watched_qty_names`, `DepthIndex.want/wanted_names`, `poller.depth_names/refresh_depth_once/run_depth_refresher(depth, cfg, lis_prices)/Evaluator/run_poller(evaluator, client, market, cfg)`, `handlers._kick_depth(depth, market)`.
