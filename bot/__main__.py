import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import BotCommand

_COMMANDS = [
    BotCommand(command="list", description="Мої стеження"),
    BotCommand(command="add", description="Додати стеження"),
    BotCommand(command="history", description="Історія ціни: /history <id>"),
    BotCommand(command="portfolio", description="Портфель і P&L"),
    BotCommand(command="buy", description="Записати купівлю: /buy назва qty ціна"),
    BotCommand(command="sold", description="Продаж: /sold <id> [qty] [ціна]"),
    BotCommand(command="setkey", description="Ключ купівлі + Trade URL"),
    BotCommand(command="balance", description="Баланс lis-skins"),
    BotCommand(command="removekey", description="Видалити ключ купівлі"),
    BotCommand(command="top", description="Топ кейсів: дешеві / розкид / рух 7д"),
    BotCommand(command="compare", description="Порівняти ціни по ринках"),
    BotCommand(command="status", description="Стан бота і джерел"),
    BotCommand(command="undo", description="Повернути видалене"),
    BotCommand(command="help", description="Довідка"),
]

from . import db
from .access import AccessMiddleware
from .config import Config
from .depth import DepthIndex
from .handlers import router
from .lis import LisClient
from .lis_buy import LisBuyClient
from .lis_cache import LisCache
from .lis_search import LisSearchClient
from .lis_ws import LisWsClient
from .market import Market
from .poller import run_depth_refresher, run_hist_pruner, run_lis_reconciler, run_poller
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
    lis_cache = LisCache()
    market = Market(client, depth, ext_sources, steam, lis_cache=lis_cache)
    if ext_sources:
        log.info("external markets: %s", ", ".join(s.key for s in ext_sources))

    lis_search = None
    lis_ws = None
    if cfg.lis_api_key:
        lis_search = LisSearchClient(cfg.lis_api_key)
        lis_ws = LisWsClient(cfg.lis_api_key, lis_cache)
        try:
            await lis_ws.start()
            log.info("lis-skins WS: connected, live price cache active")
        except Exception:
            log.warning("lis-skins WS: не вдалось підключитись, живий кеш поки порожній "
                       "(звірка через search підхопить, коли зʼявиться звʼязок)", exc_info=True)
    else:
        log.info("LIS_API_KEY не задано — живий кеш вимкнено, бот працює як раніше")

    lis_buy = LisBuyClient()
    if not cfg.secrets_key:
        log.info("SECRETS_KEY не задано — /setkey і купівля вимкнені, решта бота як раніше")

    bot = Bot(cfg.telegram_token,
              default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()
    dp["client"] = client
    dp["depth"] = depth
    dp["market"] = market
    dp["lis_cache"] = lis_cache
    dp["lis_buy"] = lis_buy
    dp["secrets_key"] = cfg.secrets_key
    if cfg.allowed_user_ids:
        mw = AccessMiddleware(cfg.allowed_user_ids)
        dp.message.outer_middleware(mw)
        dp.callback_query.outer_middleware(mw)
        log.info("access limited to %d user(s)", len(cfg.allowed_user_ids))
    dp.include_router(router)
    try:
        await bot.set_my_commands(_COMMANDS)
    except Exception:
        log.warning("set_my_commands failed", exc_info=True)

    async def _lis_names():
        names = set(await db.watched_names())
        names.update(market.case_names(120))
        return names

    tasks = [
        asyncio.create_task(run_poller(bot, client, market, cfg)),
        asyncio.create_task(run_depth_refresher(depth, cfg)),
        asyncio.create_task(run_hist_pruner()),
    ]
    if lis_search is not None:
        tasks.append(asyncio.create_task(run_lis_reconciler(lis_cache, lis_search, _lis_names)))

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
        if lis_ws is not None:
            await lis_ws.aclose()
        if lis_search is not None:
            await lis_search.aclose()
        await lis_buy.aclose()
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
