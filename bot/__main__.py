import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from . import db
from .access import AccessMiddleware
from .config import Config
from .depth import DepthIndex
from .handlers import router
from .lis import LisClient
from .market import Market
from .poller import run_depth_refresher, run_poller
from .sources import build_sources
from .steam import SteamPrices

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
    ext_sources = build_sources(cfg)
    steam = SteamPrices(cfg.steam_enabled)
    market = Market(client, depth, ext_sources, steam)
    if ext_sources:
        log.info("external markets: %s", ", ".join(s.key for s in ext_sources))

    bot = Bot(cfg.telegram_token,
              default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp["client"] = client
    dp["depth"] = depth
    dp["market"] = market
    if cfg.allowed_user_ids:
        mw = AccessMiddleware(cfg.allowed_user_ids)
        dp.message.outer_middleware(mw)
        dp.callback_query.outer_middleware(mw)
        log.info("access limited to %d user(s)", len(cfg.allowed_user_ids))
    dp.include_router(router)

    tasks = [
        asyncio.create_task(run_poller(bot, client, depth, market, cfg)),
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
        await steam.aclose()
        for s in ext_sources:
            await s.aclose()
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
