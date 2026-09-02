import asyncio
import logging

from aiogram import Bot, Dispatcher

from . import db
from .access import AccessMiddleware
from .config import Config
from .handlers import router
from .lis import LisClient
from .poller import run_poller

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("bot")


async def main():
    cfg = Config.load()
    await db.init_db(cfg.db_path)

    client = LisClient(cfg)
    await client.refresh()
    log.info("startup catalog: %d skins", len(client.names))

    bot = Bot(cfg.telegram_token)
    dp = Dispatcher()
    dp["client"] = client
    if cfg.allowed_user_ids:
        dp.message.outer_middleware(AccessMiddleware(cfg.allowed_user_ids))
        log.info("access limited to %d user(s)", len(cfg.allowed_user_ids))
    dp.include_router(router)

    poller = asyncio.create_task(run_poller(bot, client, cfg))
    try:
        await dp.start_polling(bot)
    finally:
        poller.cancel()
        try:
            await poller
        except asyncio.CancelledError:
            pass
        await client.aclose()
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
