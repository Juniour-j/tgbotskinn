import asyncio
import socket

from aiogram import Bot, Dispatcher, Router
from aiogram.types import Message
from aiohttp import ClientSession
from aiohttp.test_utils import TestClient, TestServer

from bot import handlers
from bot.config import Config
from bot import runner
from bot.runner import build_app, run, run_polling, run_webhook, webhook_params

TOKEN = "123456789:" + "A" * 35
SECRET = "s3cret"
HEADER = "X-Telegram-Bot-Api-Secret-Token"


def _cfg(port: int = 8080) -> Config:
    return Config(
        telegram_token=TOKEN, mode="webhook",
        webhook_base_url="https://bot.example.org", webhook_secret=SECRET,
        webapp_host="127.0.0.1", webapp_port=port,
    )


def _update(text: str = "ping") -> dict:
    return {
        "update_id": 1,
        "message": {
            "message_id": 1, "date": 0, "text": text,
            "chat": {"id": 7, "type": "private"},
            "from": {"id": 7, "is_bot": False, "first_name": "T"},
        },
    }


def _recording_dispatcher(seen: list, handled: asyncio.Event, gate: asyncio.Event | None = None):
    router = Router()

    @router.message()
    async def on_message(m: Message):
        if gate is not None:
            await gate.wait()
        seen.append(m.text)
        handled.set()

    dp = Dispatcher()
    dp.include_router(router)
    return dp


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class RecordingBot(Bot):
    """Справжній Bot, але без звернень до Telegram: пише виклики в self.calls."""

    def __init__(self):
        super().__init__(TOKEN)
        self.calls: list = []

    async def set_webhook(self, url, **kwargs):
        self.calls.append(("set_webhook", {"url": url, **kwargs}))
        return True

    async def delete_webhook(self, **kwargs):
        self.calls.append(("delete_webhook", kwargs))
        return True


def test_webhook_params_use_config_and_the_update_types_the_handlers_need():
    dp = Dispatcher()
    dp.include_router(handlers.router)
    params = webhook_params(dp, _cfg())
    assert params["url"] == "https://bot.example.org/webhook"
    assert params["secret_token"] == SECRET
    # без callback_query перестануть працювати всі кнопки бота
    assert {"message", "callback_query"} <= set(params["allowed_updates"])


def test_update_with_missing_or_wrong_secret_is_rejected():
    seen: list = []

    async def scenario():
        dp = _recording_dispatcher(seen, asyncio.Event())
        app = build_app(dp, Bot(TOKEN), SECRET)
        async with TestClient(TestServer(app)) as client:
            missing = await client.post("/webhook", json=_update())
            wrong = await client.post("/webhook", json=_update(), headers={HEADER: "nope"})
            return missing.status, wrong.status

    assert asyncio.run(scenario()) == (401, 401)
    assert seen == []


def test_update_with_correct_secret_is_acknowledged_and_handled():
    seen: list = []

    async def scenario():
        handled = asyncio.Event()
        dp = _recording_dispatcher(seen, handled)
        app = build_app(dp, Bot(TOKEN), SECRET)
        async with TestClient(TestServer(app)) as client:
            resp = await client.post("/webhook", json=_update("hello"), headers={HEADER: SECRET})
            await asyncio.wait_for(handled.wait(), 2)
            return resp.status

    assert asyncio.run(scenario()) == 200
    assert seen == ["hello"]


def test_slow_handler_does_not_delay_the_ack():
    """Telegram чекає ~60 с і перепосилає апдейт: відповідь має йти одразу."""
    seen: list = []

    async def scenario():
        handled, gate = asyncio.Event(), asyncio.Event()
        dp = _recording_dispatcher(seen, handled, gate)
        app = build_app(dp, Bot(TOKEN), SECRET)
        async with TestClient(TestServer(app)) as client:
            resp = await asyncio.wait_for(
                client.post("/webhook", json=_update(), headers={HEADER: SECRET}), 1)
            acked_before_handler_finished = not handled.is_set()
            gate.set()
            await asyncio.wait_for(handled.wait(), 2)
            return resp.status, acked_before_handler_finished

    assert asyncio.run(scenario()) == (200, True)


def test_run_webhook_serves_registers_and_stops_cleanly():
    port = _free_port()
    seen: list = []

    async def scenario():
        handled, stop = asyncio.Event(), asyncio.Event()
        dp = _recording_dispatcher(seen, handled)
        bot = RecordingBot()
        expected = webhook_params(dp, _cfg(port))
        task = asyncio.create_task(run_webhook(dp, bot, _cfg(port), stop=stop))
        for _ in range(150):
            if bot.calls or task.done():
                break
            await asyncio.sleep(0.02)
        assert bot.calls, "set_webhook не було викликано"
        async with ClientSession() as http:
            async with http.post(f"http://127.0.0.1:{port}/webhook", json=_update("hi"),
                                 headers={HEADER: SECRET}) as r:
                status = r.status
        await asyncio.wait_for(handled.wait(), 2)
        stop.set()
        await asyncio.wait_for(task, 5)
        return status, bot.calls, expected

    status, calls, expected = asyncio.run(scenario())
    assert status == 200 and seen == ["hi"]
    # реєстрація лишається після зупинки: Telegram накопичить апдейти на час рестарту
    assert [name for name, _ in calls] == ["set_webhook"]
    assert calls[0][1] == expected


def test_run_polling_removes_webhook_before_polling():
    order: list = []

    class Bot_(RecordingBot):
        async def delete_webhook(self, **kwargs):
            order.append("delete_webhook")
            return True

    class Dp(Dispatcher):
        async def start_polling(self, *bots, **kwargs):
            order.append("start_polling")

    asyncio.run(run_polling(Dp(), Bot_()))
    assert order == ["delete_webhook", "start_polling"]


def test_run_polling_still_polls_when_delete_webhook_fails():
    order: list = []

    class Bot_(RecordingBot):
        async def delete_webhook(self, **kwargs):
            raise RuntimeError("network down")

    class Dp(Dispatcher):
        async def start_polling(self, *bots, **kwargs):
            order.append("start_polling")

    asyncio.run(run_polling(Dp(), Bot_()))
    assert order == ["start_polling"]


def _record_runners(monkeypatch) -> list:
    called: list = []

    async def fake_polling(dp, bot):
        called.append("polling")

    async def fake_webhook(dp, bot, cfg):
        called.append("webhook")

    # обидві гілки окремо протестовані вище; тут перевіряємо лише вибір за MODE
    monkeypatch.setattr(runner, "run_polling", fake_polling)
    monkeypatch.setattr(runner, "run_webhook", fake_webhook)
    return called


def test_run_picks_webhook_when_mode_is_webhook(monkeypatch):
    called = _record_runners(monkeypatch)
    asyncio.run(run(Dispatcher(), Bot(TOKEN), _cfg()))
    assert called == ["webhook"]


def test_run_defaults_to_polling(monkeypatch):
    called = _record_runners(monkeypatch)
    cfg = Config(telegram_token=TOKEN)
    asyncio.run(run(Dispatcher(), Bot(TOKEN), cfg))
    assert called == ["polling"]
