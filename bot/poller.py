"""Фонові цикли:
- price poller: раз на poll_interval звіряє ціни/обсяги зі стеженнями по всіх ринках;
- depth refresher: раз на depth_refresh_min оновлює індекс глибини з lis-skins full.

Ціна для price-watch — найдешевша серед увімкнених ринків.
Глибина (x<шт>, /depth) — лише lis-skins.
"""
import asyncio
import logging

from . import alerts, db

log = logging.getLogger("poller")


def _ladder_str(depth, name: str, limit: int = 6) -> str:
    rungs = depth.ladder(name, limit, from_price=depth.site_price(name))
    return " · ".join(f"${p:.2f}×{q}" for p, q in rungs)


def _fmt_price_alert(name, target, market) -> str:
    qs = market.quotes(name)
    best = min(qs, key=lambda t: t[2].price) if qs else None
    lines = ["Ціна досягнута", name, f"ціль: <= ${target:.2f}"]
    if best is not None:
        _, lbl, q = best
        lines.append(f"{lbl}: ${q.price:.2f}" + (f" ({q.qty} шт)" if q.qty else ""))
        others = [f"{l} ${x.price:.2f}" for k, l, x in qs if (k, l) != (best[0], lbl)]
        if others:
            lines.append("ще: " + " · ".join(others))
        if q.url:
            lines.append(q.url)
    return "\n".join(lines)


def _fmt_qty_alert(watch, name, qty, depth, market) -> str:
    lines = [
        "Обсяг зібрався",
        name,
        f"ціль: <= ${watch['target_price']:.2f}, треба >= {watch['min_qty']} шт",
        f"зараз: {qty} шт <= ${watch['target_price']:.2f} (lis-skins)",
    ]
    sp = depth.site_price(name)
    fp = depth.fill_price(name, watch["min_qty"])
    if sp is not None:
        s = f"ціна на сайті: ${sp:.2f}"
        if fp is not None and fp > sp:
            s += f" · {watch['min_qty']} шт від ${fp:.2f}"
        lines.append(s)
    lad = _ladder_str(depth, name)
    if lad:
        lines.append(f"драбина: {lad}")
    other = [f"{l} ${q.price:.2f}" for k, l, q in market.quotes(name) if k != "lis"]
    if other:
        lines.append("інші ринки: " + " · ".join(other))
    age = depth.age_min()
    if age >= 0:
        lines.append(f"(глибина оновлена {age} хв тому)")
    return "\n".join(lines)


async def _cycle(bot, client, depth, market):
    for w in await db.all_watches():
        name = w["skin_name"]
        min_qty = w["min_qty"] or 1
        best = market.best(name)
        price = best[2].price if best else None

        if min_qty > 1:
            qty = depth.buyable_qty(name, w["target_price"])
            if qty is None:
                continue
            met = qty >= min_qty
            if met and not w["triggered"]:
                if not w["muted"]:
                    try:
                        await bot.send_message(
                            w["chat_id"], _fmt_qty_alert(w, name, qty, depth, market))
                    except Exception:
                        log.exception("send failed for watch %s", w["id"])
                    await asyncio.sleep(0.05)
                await db.mark_triggered(w["id"], price, True)
            elif not met and w["triggered"]:
                await db.mark_triggered(w["id"], price, False)
            elif price is not None and price != w["last_price"]:
                await db.set_last_price(w["id"], price)
            continue

        decision = alerts.evaluate(w["target_price"], bool(w["triggered"]), price)
        if decision == "fire":
            if w["muted"]:
                await db.set_last_price(w["id"], price)
                continue
            try:
                await bot.send_message(
                    w["chat_id"], _fmt_price_alert(name, w["target_price"], market))
            except Exception:
                log.exception("send failed for watch %s", w["id"])
            await db.mark_triggered(w["id"], price, True)
            await asyncio.sleep(0.05)
        elif decision == "rearm":
            await db.mark_triggered(w["id"], price, False)
        elif price is not None and price != w["last_price"]:
            await db.set_last_price(w["id"], price)


async def run_poller(bot, client, depth, market, cfg):
    while True:
        try:
            await client.refresh()
            await market.refresh()
            if client.ready():
                await _cycle(bot, client, depth, market)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("poll cycle error")
        await asyncio.sleep(cfg.poll_interval)


async def run_depth_refresher(depth, cfg):
    while True:
        try:
            names = await db.watched_names()
            if names:
                await depth.refresh(names)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("depth refresh cycle error")
        await asyncio.sleep(max(60, cfg.depth_refresh_min * 60))
