"""Два способи отримувати апдейти Telegram: long polling і вебхук (aiohttp)."""
from __future__ import annotations

import asyncio
import logging
import signal

from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from .config import WEBHOOK_PATH, Config

log = logging.getLogger("runner")


async def run(dp: Dispatcher, bot: Bot, cfg: Config) -> None:
    if cfg.mode == "webhook":
        await run_webhook(dp, bot, cfg)
    else:
        await run_polling(dp, bot)


async def run_polling(dp: Dispatcher, bot: Bot) -> None:
    # start_polling сам вебхук не знімає, а з активним вебхуком getUpdates віддає конфлікт
    try:
        await bot.delete_webhook()
    except Exception:
        log.warning("delete_webhook failed", exc_info=True)
    await dp.start_polling(bot)


def webhook_params(dp: Dispatcher, cfg: Config) -> dict:
    return {
        "url": cfg.webhook_url,
        "secret_token": cfg.webhook_secret,
        # polling виводить типи апдейтів сам, для вебхука — явно (інакше не прийдуть callback_query)
        "allowed_updates": dp.resolve_used_update_types(),
    }


def build_app(dp: Dispatcher, bot: Bot, secret: str) -> web.Application:
    app = web.Application()
    # відповідь Telegram одразу, обробник доробляє у фоні (повільні хендлери не викликають повторних доставок)
    SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=secret,
                         handle_in_background=True).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)
    return app


async def run_webhook(dp: Dispatcher, bot: Bot, cfg: Config,
                      stop: asyncio.Event | None = None) -> None:
    if stop is None:
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGINT, signal.SIGTERM):
            try:
                loop.add_signal_handler(sig, stop.set)
            except NotImplementedError:  # Windows: зупинка через KeyboardInterrupt
                pass
    runner = web.AppRunner(build_app(dp, bot, cfg.webhook_secret))
    await runner.setup()
    try:
        # спершу сервер, потім реєстрація — щоб перший апдейт не прилетів у порожнечу
        await web.TCPSite(runner, cfg.webapp_host, cfg.webapp_port).start()
        await bot.set_webhook(**webhook_params(dp, cfg))
        log.info("webhook set: %s (listening on %s:%s)",
                 cfg.webhook_url, cfg.webapp_host, cfg.webapp_port)
        await stop.wait()
    finally:
        # вебхук навмисно НЕ знімаємо: на час рестарту Telegram накопичує апдейти
        await runner.cleanup()
