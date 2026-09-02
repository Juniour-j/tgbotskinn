"""Фоновий цикл: раз на poll_interval оновлює прайс і звіряє зі стеженнями."""
import asyncio
import logging

from . import alerts, db

log = logging.getLogger("poller")


def _fmt_alert(watch, item) -> str:
    lines = [
        "Ціна досягнута",
        item.name,
        f"ціль: <= ${watch['target_price']:.2f}",
        f"зараз: ${item.price:.2f} ({item.count} шт)",
    ]
    if item.url:
        lines.append(item.url)
    return "\n".join(lines)


async def _cycle(bot, client):
    for w in await db.all_watches():
        item = client.lookup(w["skin_name"])
        price = item.price if item else None
        decision = alerts.evaluate(w["target_price"], bool(w["triggered"]), price)

        if decision == "fire":
            if w["muted"]:
                await db.set_last_price(w["id"], price)
                continue
            try:
                await bot.send_message(w["chat_id"], _fmt_alert(w, item))
            except Exception:
                log.exception("send failed for watch %s", w["id"])
            await db.mark_triggered(w["id"], price, True)
            await asyncio.sleep(0.05)
        elif decision == "rearm":
            await db.mark_triggered(w["id"], price, False)
        elif price is not None and price != w["last_price"]:
            await db.set_last_price(w["id"], price)


async def run_poller(bot, client, cfg):
    while True:
        try:
            await client.refresh()
            if client.ready():
                await _cycle(bot, client)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("poll cycle error")
        await asyncio.sleep(cfg.poll_interval)
