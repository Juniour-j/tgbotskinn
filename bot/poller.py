"""Фонові цикли:
- price poller: раз на poll_interval звіряє ціни/обсяги зі стеженнями;
- depth refresher: раз на depth_refresh_min оновлює індекс з повного експорту
  (api_csgo_full.json) для всіх назв, що є в стеженнях.

Ціна береться з повного експорту (збігається з сайтом). Короткий csgo.json —
лише запасний варіант, поки глибина для назви ще не завантажилась.
"""
import asyncio
import logging

from . import alerts, db

log = logging.getLogger("poller")


def _ladder_str(depth, name: str, limit: int = 6) -> str:
    rungs = depth.ladder(name, limit)
    return " · ".join(f"${p:.2f}×{q}" for p, q in rungs)


def _eff_price(depth, item, name: str):
    """Актуальна мін ціна: спершу з повного експорту, інакше з csgo.json."""
    f = depth.floor(name)
    if f is not None:
        return f, False  # (ціна, чи_приблизна)
    if item is not None:
        return item.price, True
    return None, True


def _fmt_price_alert(name, target, price, approx, item) -> str:
    lines = [
        "Ціна досягнута",
        name,
        f"ціль: <= ${target:.2f}",
        f"зараз: ${price:.2f}" + (" (орієнтовно)" if approx else ""),
    ]
    if item is not None and item.url:
        lines.append(item.url)
    return "\n".join(lines)


def _fmt_qty_alert(watch, name, qty, depth, item) -> str:
    lines = [
        "Обсяг зібрався",
        name,
        f"ціль: <= ${watch['target_price']:.2f}, треба >= {watch['min_qty']} шт",
        f"зараз: {qty} шт <= ${watch['target_price']:.2f}",
    ]
    f = depth.floor(name)
    if f is not None:
        lines.append(f"мін ціна зараз: ${f:.2f}")
    lad = _ladder_str(depth, name)
    if lad:
        lines.append(f"драбина: {lad}")
    if item is not None and item.url:
        lines.append(item.url)
    age = depth.age_min()
    if age >= 0:
        lines.append(f"(глибина оновлена {age} хв тому)")
    return "\n".join(lines)


async def _cycle(bot, client, depth):
    for w in await db.all_watches():
        name = w["skin_name"]
        item = client.lookup(name)
        min_qty = w["min_qty"] or 1
        price, approx = _eff_price(depth, item, name)

        if min_qty > 1:
            qty = depth.qty_at_or_below(name, w["target_price"])
            if qty is None:
                continue  # глибина для цієї назви ще не завантажена
            met = qty >= min_qty
            if met and not w["triggered"]:
                if not w["muted"]:
                    try:
                        await bot.send_message(w["chat_id"], _fmt_qty_alert(w, name, qty, depth, item))
                    except Exception:
                        log.exception("send failed for watch %s", w["id"])
                    await asyncio.sleep(0.05)
                await db.mark_triggered(w["id"], price, True)
            elif not met and w["triggered"]:
                await db.mark_triggered(w["id"], price, False)
            elif price is not None and price != w["last_price"]:
                await db.set_last_price(w["id"], price)
            continue

        # стеження за ціною
        decision = alerts.evaluate(w["target_price"], bool(w["triggered"]), price)
        if decision == "fire":
            if w["muted"]:
                await db.set_last_price(w["id"], price)
                continue
            try:
                await bot.send_message(
                    w["chat_id"],
                    _fmt_price_alert(name, w["target_price"], price, approx, item),
                )
            except Exception:
                log.exception("send failed for watch %s", w["id"])
            await db.mark_triggered(w["id"], price, True)
            await asyncio.sleep(0.05)
        elif decision == "rearm":
            await db.mark_triggered(w["id"], price, False)
        elif price is not None and price != w["last_price"]:
            await db.set_last_price(w["id"], price)


async def run_poller(bot, client, depth, cfg):
    while True:
        try:
            await client.refresh()
            if client.ready():
                await _cycle(bot, client, depth)
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
