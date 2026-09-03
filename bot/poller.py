"""Фонові цикли:
- price poller: раз на poll_interval звіряє ціни/обсяги зі стеженнями по всіх ринках;
- depth refresher: раз на depth_refresh_min оновлює індекс глибини з lis-skins full.

Ціна для price-watch — найдешевша серед увімкнених ринків.
Глибина (x<шт>, /depth) — лише lis-skins.
"""
import asyncio
import html
import logging

from . import alerts, db, keyboards

log = logging.getLogger("poller")


def _esc(s) -> str:
    return html.escape(str(s))


def _n(x) -> str:
    return f"{int(x):,}".replace(",", " ")


def _price_alert(name, target, market):
    qs = sorted(market.quotes(name), key=lambda t: t[2].price)
    best = qs[0] if qs else None
    lines = [f"🔔 <b>Ціль досягнута</b>", f"<b>{_esc(name)}</b>", ""]
    kb = None
    if best is not None:
        _, lbl, q = best
        lines.append(f"<b>${q.price:.2f}</b> на {lbl}   (ціль ≤ ${target:.2f})")
        others = [f"{l} ${x.price:.2f}" for _, l, x in qs[1:]]
        if others:
            lines.append("інші: " + " · ".join(others))
        if q.url:
            kb = keyboards.alert_kb(lbl, q.url)
    return "\n".join(lines), kb


def _qty_alert(watch, name, qty, depth, market):
    t = watch["target_price"]
    lines = [
        "🔔 <b>Обсяг зібрався</b>",
        f"<b>{_esc(name)}</b>",
        "",
        f"можна купити <b>{_n(qty)} шт</b> по ≤ ${t:.2f}  (треба {watch['min_qty']})",
    ]
    sp = depth.site_price(name)
    fp = depth.fill_price(name, watch["min_qty"])
    parts = []
    if sp is not None:
        parts.append(f"lis-skins ${sp:.2f}")
    if fp is not None:
        parts.append(f"набрати {watch['min_qty']} від ${fp:.2f}")
    if parts:
        lines.append("  ·  ".join(parts))
    other = [f"{l} ${q.price:.2f}" for k, l, q in market.quotes(name) if k != "lis"]
    if other:
        lines.append("інші ринки: " + " · ".join(other))
    q_lis = next((q for k, _, q in market.quotes(name) if k == "lis"), None)
    kb = keyboards.alert_kb("lis-skins", q_lis.url) if q_lis and q_lis.url else None
    return "\n".join(lines), kb


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
                    txt, kb = _qty_alert(w, name, qty, depth, market)
                    try:
                        await bot.send_message(w["chat_id"], txt, reply_markup=kb)
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
            txt, kb = _price_alert(name, w["target_price"], market)
            try:
                await bot.send_message(w["chat_id"], txt, reply_markup=kb)
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
