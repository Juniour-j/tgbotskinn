import asyncio
import logging

from aiogram import Bot, Dispatcher

from . import db
from .access import AccessMiddleware
from .config import Config
from .depth import DepthIndex
from .handlers import router
from .lis import LisClient
from .poller import run_depth_refresher, run_poller

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

    depth = DepthIndex(cfg)

    bot = Bot(cfg.telegram_token)
    dp = Dispatcher()
    dp["client"] = client
    dp["depth"] = depth
    if cfg.allowed_user_ids:
        mw = AccessMiddleware(cfg.allowed_user_ids)
        dp.message.outer_middleware(mw)
        dp.callback_query.outer_middleware(mw)
        log.info("access limited to %d user(s)", len(cfg.allowed_user_ids))
    dp.include_router(router)

    tasks = [
        asyncio.create_task(run_poller(bot, client, depth, cfg)),
        asyncio.create_task(run_depth_refresher(depth, cfg)),
    ]
    try:
        await dp.start_polling(bot)
    finally:
        for t in tasks:
            t.cancel()
        for t in tasks:
            try:
                await t
            except asyncio.CancelledError:
                pass
        await client.aclose()
        await depth.aclose()
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
