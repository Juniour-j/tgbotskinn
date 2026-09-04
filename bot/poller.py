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


def _price_alert(wid, name, target, direction, market):
    qs = sorted(market.quotes(name), key=lambda t: t[2].price)
    best = qs[0] if qs else None
    sign = "≥" if direction == "up" else "≤"
    lines = [f"🔔 <b>Ціль досягнута</b>  ·  <b>{_esc(name)}</b>"]
    kb, one = None, ""
    if best is not None:
        _, lbl, q = best
        bo = f"  ·  скуп ${q.buy_order:.2f}" if q.buy_order else ""
        inner = [f"<b>${q.price:.2f}</b> на {lbl}{bo}   ·   ціль {sign} ${target:.2f}"]
        others = [f"{l} ${x.price:.2f}" for _, l, x in qs[1:]]
        if others:
            inner.append("інші: " + " · ".join(others))
        lines.append("<blockquote>" + "\n".join(inner) + "</blockquote>")
        kb = keyboards.alert_kb(lbl, q.url, wid)
        one = f"<b>#{wid} {_esc(name)}</b> — <b>${q.price:.2f}</b> {lbl} (ціль {sign} ${target:.2f})"
    return "\n".join(lines), kb, one


def _qty_alert(watch, name, qty, depth, market):
    t = watch["target_price"]
    inner = [f"можна купити <b>{_n(qty)} шт</b> по ≤ ${t:.2f}   ·   треба {watch['min_qty']}"]
    sp = depth.site_price(name)
    fp = depth.fill_price(name, watch["min_qty"])
    parts = []
    if sp is not None:
        parts.append(f"lis-skins ${sp:.2f}")
    if fp is not None:
        parts.append(f"набрати {watch['min_qty']} від ${fp:.2f}")
    if parts:
        inner.append("  ·  ".join(parts))
    other = [f"{l} ${q.price:.2f}" for k, l, q in market.quotes(name) if k != "lis"]
    if other:
        inner.append("інші ринки: " + " · ".join(other))
    lines = [f"🔔 <b>Обсяг зібрався</b>  ·  <b>{_esc(name)}</b>",
             "<blockquote>" + "\n".join(inner) + "</blockquote>"]
    q_lis = next((q for k, _, q in market.quotes(name) if k == "lis"), None)
    url = q_lis.url if q_lis else ""
    kb = keyboards.alert_kb("lis-skins", url, watch["id"])
    one = f"<b>#{watch['id']} {_esc(name)}</b> — {_n(qty)} шт по ≤ ${t:.2f} (треба {watch['min_qty']})"
    return "\n".join(lines), kb, one


async def _cycle(bot, client, depth, market):
    fired: dict[int, list] = {}  # chat_id -> [(text, kb, one_liner)]
    seen: dict[str, float] = {}  # name -> best price (для історії)
    for w in await db.all_watches():
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

    # історія цін: стеження + універсум кейсів (для «топ · рух за 7д»)
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

    for chat_id, items in fired.items():
        if len(items) == 1:
            txt, kb, _ = items[0]
        else:
            body = "\n".join(f"▎{one}" for _, _, one in items)
            txt, kb = f"🔔 <b>Спрацювало ({len(items)})</b>\n{body}", None
        try:
            await bot.send_message(chat_id, txt, reply_markup=kb)
        except Exception:
            log.exception("alert send failed for chat %s", chat_id)
        await asyncio.sleep(0.05)


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


async def run_hist_pruner(keep_days: int = 70):
    """Раз на добу чистить старі погодинні знімки цін."""
    while True:
        try:
            n = await db.prune_prices(keep_days)
            if n:
                log.info("prune_prices: видалено %d записів", n)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("prune_prices cycle error")
        await asyncio.sleep(24 * 3600)
