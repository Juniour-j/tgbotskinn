"""Команди, текст і кнопки Telegram-бота."""
from __future__ import annotations

import asyncio
import html
import logging
import re
import time

from aiogram import F, Router
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from . import alerts, db, keyboards, matcher

log = logging.getLogger("handlers")
router = Router()

HELP = (
    "<b>Що я вмію</b>\n"
    "Слідкую за цінами скінів CS2 і пишу, коли ціна впаде до потрібної.\n"
    "Порівнюю 3 ринки — <b>lis-skins</b>, <b>market.csgo</b>, <b>Skinport</b> — беру найдешевший.\n\n"
    "<b>Як додати</b>\n"
    "Напиши одним рядком назву й ціль у $:\n"
    "<blockquote><code>Kilowatt Case 0.13</code>\n"
    "<code>AWP | Asiimov (Field-Tested) 55</code></blockquote>"
    "→ сповіщу, щойно будь-де стане ≤ цієї ціни.\n\n"
    "<b>За обсягом</b> — додай <code>x&lt;кількість&gt;</code>:\n"
    "<blockquote><code>Kilowatt Case 0.13 x200</code></blockquote>"
    "→ сповіщу, коли на lis-skins можна <b>купити</b> 200+ шт по ≤ $0.13.\n\n"
    "<b>На зростання</b> (для продажу) — додай <code>вгору</code>:\n"
    "<blockquote><code>Kilowatt Case 0.20 вгору</code></blockquote>\n"
    "Не знаєш назву — напиши частину («kilowatt»), покажу варіанти.\n\n"
    "У списку: <b>📊 Глибина</b> і <b>⚙️ Керувати</b> "
    "(🔗 відкрити · ✏️ змінити ціль · 🔀 порівняти · 🔕 тиша · 🗑 видалити).\n"
    "Ще: <b>💸 Топ</b>, <b>📈 Статус</b>, <code>/compare назва</code>."
)

_ADD_PROMPT = (
    "<b>Напиши назву скіна і ціль у $</b>\n\n"
    "<blockquote><code>Kilowatt Case 0.13</code></blockquote>"
    "→ сповіщу, коли ціна впаде до $0.13\n\n"
    "<blockquote><code>Kilowatt Case 0.13 x200</code></blockquote>"
    "→ сповіщу, коли можна купити 200+ шт по ≤ $0.13\n\n"
    "Не знаєш назву — напиши частину, покажу варіанти.\n"
    "Або обери популярний кейс кнопкою ⬇️"
)

_QTY_RE = re.compile(r"^[xхXХ*](\d+)$")
_UP_WORDS = ("вгору", "up", "↑", "вище", ">")
_DOWN_WORDS = ("вниз", "down", "↓", "нижче", "<")

_STARTED = time.time()

# короткочасний стан у памʼяті (втрачається при рестарті — не критично)
_pending_price: dict[int, str] = {}     # user_id -> canonical name, чекаємо ціну
_pending_edit: dict[int, int] = {}      # user_id -> watch_id, чекаємо нову ціль
_pending_compare: set[int] = set()      # user_id -> чекаємо назву для /compare
_last_search: dict[int, list] = {}      # user_id -> список знайдених назв
_sort_mode: dict[int, str] = {}         # user_id -> "state"|"price"|"name"
_last_deleted: dict[int, dict] = {}     # user_id -> {skin_name,target_price,min_qty,direction}
_last_top: dict[int, list] = {}         # user_id -> назви з останнього /top


async def _show(cb: CallbackQuery, text: str, kb, toast: str | None = None):
    """Перемалювати екран у тому ж повідомленні (fallback — нове)."""
    try:
        await cb.message.edit_text(text, reply_markup=kb)
    except TelegramBadRequest as e:
        if "not modified" not in str(e).lower():
            await cb.message.answer(text, reply_markup=kb)
    except Exception:
        await cb.message.answer(text, reply_markup=kb)
    await cb.answer(toast or None)


# ---------- парсери ----------

def _split_price(tok: str):
    """('0.13', 'up'|'down'|None) — визначає напрямок за префіксом >/<."""
    t = tok.strip().lstrip("$")
    if t[:1] == ">":
        return t[1:], "up"
    if t[:1] == "<":
        return t[1:], "down"
    return t, None


def _parse_watch_args(args: str):
    toks = args.split()
    if len(toks) < 2:
        raise ValueError
    direction = "down"
    if toks[-1].lower() in _UP_WORDS:
        direction, toks = "up", toks[:-1]
    elif toks[-1].lower() in _DOWN_WORDS:
        toks = toks[:-1]
    if len(toks) < 2:
        raise ValueError
    qty = 1
    m = _QTY_RE.match(toks[-1])
    if m and len(toks) >= 3:
        qty = int(m.group(1))
        toks = toks[:-1]
    ptok, pdir = _split_price(toks[-1])
    if pdir:
        direction = pdir
    price = float(ptok.replace(",", "."))
    name = " ".join(toks[:-1]).strip()
    if not name or price <= 0 or qty < 1:
        raise ValueError
    return name, price, qty, direction


def _parse_price_qty(s: str):
    toks = s.split()
    direction = "down"
    if toks and toks[-1].lower() in _UP_WORDS:
        direction, toks = "up", toks[:-1]
    elif toks and toks[-1].lower() in _DOWN_WORDS:
        toks = toks[:-1]
    qty = 1
    m = _QTY_RE.match(toks[-1]) if toks else None
    if m and len(toks) >= 2:
        qty = int(m.group(1))
        toks = toks[:-1]
    if len(toks) != 1:
        raise ValueError
    ptok, pdir = _split_price(toks[0])
    if pdir:
        direction = pdir
    price = float(ptok.replace(",", "."))
    if price <= 0 or qty < 1:
        raise ValueError
    return price, qty, direction


# ---------- спільні екрани ----------

def _menu_text() -> str:
    return (
        "<b>Меню</b>\n\n"
        "📋 <b>Мої стеження</b> — список + керування\n"
        "➕ <b>Додати</b> — нове стеження за ціною\n"
        "🔀 <b>Порівняти ціни</b> — по всіх ринках для одного скіна\n"
        "🔎 <b>Знайти скін</b> — пошук за назвою\n"
        "❓ <b>Довідка</b> — як це працює"
    )


_SHORT = {"lis-skins": "lis", "market.csgo": "mcsgo", "skinport": "sp"}


def _esc(s) -> str:
    return html.escape(str(s))


def _n(x) -> str:
    return f"{int(x):,}".replace(",", " ")


def _money(x) -> str:
    return "$" + f"{x:,.2f}".replace(",", " ")


def _mkt_line(name: str, market, short: bool = False) -> str:
    qs = sorted(market.quotes(name), key=lambda t: t[2].price)
    return "  ·  ".join(
        f"{(_SHORT.get(lbl, lbl) if short else lbl)} <b>${q.price:.2f}</b>"
        for _, lbl, q in qs
    )


def _state(row, met: bool) -> str:
    ml = db.muted_label(row)
    if ml:
        return ml
    if met:
        return "✅ ціль досягнута" + (" · сповіщено" if row["triggered"] else "")
    return "⏳ чекаю"


def _icon(row, met: bool) -> str:
    return "🔕" if db.is_muted(row) else ("✅" if met else "⏳")


def _sign(row) -> str:
    return "≥" if row["direction"] == "up" else "≤"


async def _list_view(user_id: int, market, page: int = 0):
    rows = await db.list_watches(user_id)
    if not rows:
        return ("<b>Ще нема жодного стеження.</b>\n\n"
                "Тисни ➕ Додати або просто напиши назву й ціль:\n"
                "<blockquote><code>Kilowatt Case 0.13</code></blockquote>"), keyboards.add_kb()
    depth = market.depth
    sort = _sort_mode.get(user_id, "state")
    entries = []  # (row, block, met, cheapest_price)
    for r in rows:
        name = _esc(r["skin_name"])
        t, sg = r["target_price"], _sign(r)
        mkt = _mkt_line(r["skin_name"], market, short=True) or "ціни ще нема"
        best = market.best(r["skin_name"])
        cheap = best[2].price if best else 1e12
        if r["min_qty"] > 1:
            have = depth.buyable_qty(r["skin_name"], t)
            met = have is not None and have >= r["min_qty"]
            fp = depth.fill_price(r["skin_name"], r["min_qty"])
            now = f"{_n(have)} шт" if have is not None else "…"
            fill = f" · набрати {r['min_qty']} від <b>${fp:.2f}</b>" if fp else ""
            block = (f"<blockquote>{_icon(r, met)} <b>#{r['id']} {name}</b>  · опт ≥{r['min_qty']}\n"
                     f"ціль ≤ ${t:.2f}  ·  зараз {now}{fill}\n<i>{mkt}</i></blockquote>")
        else:
            met = best is not None and alerts.hit(t, best[2].price, r["direction"])
            if best is not None:
                gap = best[2].price - t
                if r["direction"] == "up":
                    tail = "вище цілі" if gap >= 0 else f"ще +${-gap:.2f}"
                else:
                    tail = "нижче цілі" if gap <= 0 else f"ще −${gap:.2f}"
                now = f"<b>${best[2].price:.2f}</b> {_SHORT.get(best[1], best[1])} · {tail}"
            else:
                now = "?"
            block = (f"<blockquote>{_icon(r, met)} <b>#{r['id']} {name}</b>\n"
                     f"ціль {sg} ${t:.2f}  ·  зараз {now}\n<i>{mkt}</i></blockquote>")
        entries.append((r, block, met and not db.is_muted(r), cheap))

    def _grp(e):
        if db.is_muted(e[0]):
            return 2
        return 0 if e[2] else 1

    if sort == "price":
        entries.sort(key=lambda e: e[3])
    elif sort == "name":
        entries.sort(key=lambda e: e[0]["skin_name"].lower())
    else:
        entries.sort(key=lambda e: (_grp(e), e[0]["id"]))

    pages = (len(entries) + keyboards.PAGE - 1) // keyboards.PAGE
    page = max(0, min(page, pages - 1))
    chunk = entries[page * keyboards.PAGE:(page + 1) * keyboards.PAGE]
    done = sum(1 for _, _, a, _ in entries if a)
    has_trig = any(e[0]["triggered"] for e in entries)
    hdr = f"<b>Стеження</b> · {len(entries)}" + (f"   ✅ {done}" if done else "")

    _GH = {0: "✅ Готові", 1: "⏳ Чекають", 2: "🔕 Тиша"}
    parts, last = [], None
    for e in chunk:
        if sort == "state" and _grp(e) != last:
            last = _grp(e)
            parts.append(f"<b>{_GH[last]}</b>")
        parts.append(e[1])
    kb = keyboards.list_kb([e[0] for e in chunk], page, pages, sort, has_trig,
                           undo=user_id in _last_deleted)
    return hdr + "\n" + "\n".join(parts), kb


async def _status_view(market, client, depth):
    up = int(time.time() - _STARTED)
    d, rem = divmod(up, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    upt = (f"{d}д " if d else "") + f"{h}г {m}хв"
    n_w = await db.count_watches()
    lines = [
        "<b>📈 Статус</b>",
        f"аптайм: {upt}",
        f"стежень: {n_w}",
        f"каталог lis: {len(client.names)} назв",
        f"глибина lis: {'—' if depth.age_min() < 0 else f'{depth.age_min()} хв тому'}",
    ]
    for s in market.sources:
        st = s.status()
        age = "—" if st["age_s"] < 0 else f"{st['age_s'] // 60} хв тому"
        warn = f"  ⚠️ помилок: {st['fails']}" if st["fails"] else ""
        lines.append(f"{s.label}: {st['items']} поз · {age}{warn}")
    lines.append(f"Steam: {'увімкнено' if market.steam and market.steam.enabled else 'вимкнено'}")
    return "\n".join(lines), keyboards.back_kb()


async def _top_view(uid: int, market, mode: str):
    if mode == "spread":
        rows = market.top_spread(15)
        if not rows:
            return ("<b>Топ · розкид</b>\n\nНедостатньо даних (треба 2+ ринки).",
                    keyboards.top_kb(mode))
        names = [r[0] for r in rows]
        body = [f"{p:>4.0f}%  {_esc(n)}  —  {lo_l} {_money(lo)} → {hi_l} {_money(hi)}"
                for n, lo_l, lo, hi_l, hi, p in rows]
        head = "<b>↔️ Топ розкид між ринками</b>"
    else:
        rows = market.top_cheapest(15)
        if not rows:
            return "<b>Топ · найдешевші</b>\n\nЩе нема даних.", keyboards.top_kb(mode)
        names = [r[0] for r in rows]
        body = [f"{_money(p):>8}  {_esc(n)}  ({lbl})" for n, lbl, p in rows]
        head = "<b>💸 Найдешевші зараз</b>"
    _last_top[uid] = names
    return (head + "\n<pre>" + _esc("\n".join(body)) + "</pre>",
            keyboards.top_kb(mode, names))


def _open_links(name: str, market):
    out = []
    for _, lbl, q in sorted(market.quotes(name), key=lambda t: t[2].price):
        if q.url:
            out.append((lbl, q.url))
    return out


def _mkt_row(lbl: str, q, first: bool) -> str:
    mark = "▸ " if first else "  "
    line = f"{mark}{lbl:<12}{_money(q.price):>10}"
    if q.buy_order:
        line += f"   скуп {_money(q.buy_order)}"
    return line


def _target_suggestions(price: float, direction: str):
    """3 підказані цілі навколо поточної ціни."""
    if direction == "up":
        raw = [price, price * 1.05, price * 1.10]
    else:
        raw = [price, price * 0.95, price * 0.90]
    seen, out = set(), []
    for p in raw:
        r = round(p, 2)
        if r > 0 and r not in seen:
            seen.add(r)
            out.append(r)
    return out


async def _ask_price(cb, name: str, market, edit_wid=None, direction="down"):
    best = market.best(name)
    txt = (f"«{_esc(name)}»\nНадішли ціль у $ — напр. <code>0.13</code>\n"
           "(або <code>0.13 x200</code> опт, <code>0.20 вгору</code> на зростання)")
    kb = None
    if best is not None:
        kb = keyboards.target_kb(_target_suggestions(best[2].price, direction), edit_wid)
        txt += f"\n\nАбо тапни підказку (зараз ${best[2].price:.2f}):"
    await cb.message.answer(txt, reply_markup=kb)
    await cb.answer()


async def _steam_followup(cb, name, market, render):
    """Дотягнути ціну Steam і перемалювати екран, коли зʼявиться."""
    try:
        if not (market.steam and market.steam.enabled):
            return
        if market.steam.cached(name) is not None:
            return
        got = await market.steam.get(name)
        if got is None:
            return
        text, kb = await render()
        try:
            await cb.message.edit_text(text, reply_markup=kb)
        except Exception:
            pass
    except Exception:
        pass


async def _warm_steam(market, name):
    try:
        await market.steam.get(name)
    except Exception:
        pass


def _steam_note(name: str, best_price, market) -> str:
    if not (market.steam and market.steam.enabled):
        return ""
    sp = market.steam.cached(name)
    if sp is None:
        asyncio.create_task(_warm_steam(market, name))  # прогріємо на наступний раз
        return ""
    if not sp:
        return ""
    if best_price and sp > 0:
        return f"Steam ${sp:.2f}  ·  найдешевше −{(sp - best_price) / sp * 100:.0f}%"
    return f"Steam ${sp:.2f}"


async def _watch_card(user_id: int, wid: int, market):
    w = await db.get_watch(user_id, wid)
    if w is None:
        return f"Немає стеження #{wid}.", keyboards.back_kb()
    name, t, depth = w["skin_name"], w["target_price"], market.depth
    best = market.best(name)
    inner = []
    if w["min_qty"] > 1:
        have = depth.buyable_qty(name, t)
        met = have is not None and have >= w["min_qty"]
        inner.append(f"<b>Ціль</b>  ≥ {w['min_qty']} шт по ≤ <b>${t:.2f}</b>  (lis-skins)")
        inner.append(f"<b>Стан</b>  {_state(w, met)}")
        if have is not None:
            inner.append(f"<b>Зараз</b>  {_n(have)} шт по ≤ ${t:.2f}")
        fp = depth.fill_price(name, w["min_qty"])
        if fp is not None:
            inner.append(f"<b>Набір</b>  {w['min_qty']} шт від <b>${fp:.2f}</b>")
    else:
        met = best is not None and alerts.hit(t, best[2].price, w["direction"])
        inner.append(f"<b>Ціль</b>  {_sign(w)} <b>${t:.2f}</b>")
        inner.append(f"<b>Стан</b>  {_state(w, met)}")
        if best is not None:
            gap = best[2].price - t
            if w["direction"] == "up":
                note = "" if gap >= 0 else f"  ·  ще +${-gap:.2f}"
            else:
                note = "" if gap <= 0 else f"  ·  ще −${gap:.2f}"
            inner.append(f"<b>Зараз</b>  <b>${best[2].price:.2f}</b> — {best[1]}{note}")
    lines = [f"<b>#{wid} · {_esc(name)}</b>", "",
             "<blockquote>" + "\n".join(inner) + "</blockquote>"]
    qs = sorted(market.quotes(name), key=lambda x: x[2].price)
    if qs:
        rows = [_mkt_row(lbl, q, i == 0) for i, (_, lbl, q) in enumerate(qs)]
        lines.append("<pre>" + _esc("\n".join(rows)) + "</pre>")
        sn = _steam_note(name, qs[0][2].price, market)
        if sn:
            lines.append(sn)
    return ("\n".join(lines),
            keyboards.watch_kb(wid, db.is_muted(w), _open_links(name, market)))


def _bar(q: int, mx: int, width: int = 10) -> str:
    filled = round(q / mx * width) if mx else 0
    return "█" * filled + "░" * (width - filled)


async def _depth_view(user_id: int, wid: int, client, depth, market):
    w = await db.get_watch(user_id, wid)
    if w is None:
        return f"Немає стеження #{wid}.", keyboards.back_kb()
    name = w["skin_name"]
    if not depth.has(name):
        asyncio.create_task(_kick_depth(depth))
        return ("<b>Глибина ще вантажиться</b>\n"
                "Оновлюється раз на ~10 хв. Спробуй за хвилину."), keyboards.depth_kb(wid)
    sp = depth.site_price(name)
    rungs = depth.ladder(name, 12, from_price=sp)
    mx = max((q for _, q in rungs), default=1)
    out = [f"<b>📊 {_esc(name)}</b>  ·  lis-skins"]
    if sp is not None:
        out.append(f"ціна на сайті <b>${sp:.2f}</b>  ·  оновлено {depth.age_min()} хв тому")
    body = [f"{'ціна':<6}{'шт':>8} {'сумарно':>9}", "─" * 30]
    cum = 0
    for p, q in rungs:
        cum += q
        wall = "  ◀" if q == mx else ""
        body.append(f"${p:<5.2f}{_n(q):>8} {_n(cum):>9}  {_bar(q, mx)}{wall}")
    out.append("<pre>" + _esc("\n".join(body)) + "</pre>")
    q_want = w["min_qty"] if w["min_qty"] > 1 else 50
    fill = depth.fill_price(name, q_want)
    have = depth.buyable_qty(name, w["target_price"])
    if fill is not None:
        out.append(f"набрати {q_want} шт: від <b>${fill:.2f}</b>")
    tick = " ✅" if (have is not None and w["min_qty"] > 1 and have >= w["min_qty"]) else ""
    out.append(f"по ≤ ${w['target_price']:.2f}: <b>{_n(have or 0)} шт</b>"
               + (f" (ціль x{w['min_qty']}{tick})" if w["min_qty"] > 1 else ""))
    other = [(lbl, q) for k, lbl, q in market.quotes(name) if k != "lis"]
    if other:
        out.append("")
        out.append("інші ринки: " + "  ·  ".join(
            f"{lbl} <b>${q.price:.2f}</b>" for lbl, q in other))
    return "\n".join(out), keyboards.depth_kb(wid)


async def _compare_view(name: str, market):
    qs = sorted(market.quotes(name), key=lambda t: t[2].price)
    if not qs:
        return f"<b>{_esc(name)}</b>\n\nЦіни ніде не знайшов.", keyboards.back_kb()
    rows = []
    for i, (_, lbl, q) in enumerate(qs):
        mark = "▸ " if i == 0 else "  "
        line = f"{mark}{lbl:<12}{_money(q.price):>10}"
        if q.buy_order:
            line += f"   скуп {_money(q.buy_order)}"
        if q.qty:
            line += f"   {_n(q.qty)} шт"
        rows.append(line)
    out = [f"<b>🔀 {_esc(name)}</b>",
           "<pre>" + _esc("\n".join(rows)) + "</pre>"]
    sn = _steam_note(name, qs[0][2].price, market)
    if sn:
        out.append(sn)
    if len(qs) > 1:
        lo, hi = qs[0][2].price, qs[-1][2].price
        pct = (hi - lo) / hi * 100 if hi else 0
        out.append(f"найдешевше <b>{qs[0][1]}</b> — на {pct:.0f}% нижче "
                   f"(розкид ${hi - lo:.2f})")
    return "\n".join(out), keyboards.back_kb()


async def _add_watch(uid: int, chat_id: int, raw_name: str, price: float,
                     qty: int, direction: str, client, depth, market):
    canonical, exact = matcher.resolve(raw_name, client.names)
    if canonical is None:
        sugg = [n for n, s in matcher.best_matches(raw_name, client.names, 8)
                if s > matcher.MIN_SUGGEST]
        _last_search[uid] = sugg
        if sugg:
            items = [(n, market.best(n)[2].price if market.best(n) else None)
                     for n in sugg]
            return (f"«{_esc(raw_name)}» — не впевнений. Вибери:", keyboards.find_kb(items))
        return (f"Не знайшов «{_esc(raw_name)}». Напиши інакше.", keyboards.menu_kb())

    wid, action = await db.add_watch(uid, chat_id, canonical, price,
                                    min_qty=qty, direction=direction)
    if wid is None:
        return "Не вдалося зберегти. Спробуй ще раз.", keyboards.menu_kb()

    sg = "≥" if direction == "up" else "≤"
    head = "✅ <b>Стежу</b>" if action == "created" else "✏️ <b>Оновив стеження</b>"
    lines = [f"{head} #{wid}", f"<b>{_esc(canonical)}</b>"]
    if not exact:
        lines.append("<i>(назву підібрав за схожістю)</i>")
    lines.append("")

    best = market.best(canonical)
    if qty > 1:
        lines.append(f"Ціль: ≥ {qty} шт по ≤ <b>${price:.2f}</b>  (lis-skins)")
        have = depth.buyable_qty(canonical, price)
        if have is None:
            lines.append("Зараз: глибина ще вантажиться (~хвилина).")
            asyncio.create_task(_kick_depth(depth))
        elif have >= qty:
            lines.append(f"Зараз: <b>{_n(have)} шт</b> по ≤ ${price:.2f} — умова вже виконана ✅")
        else:
            fp = depth.fill_price(canonical, qty)
            lines.append(f"Зараз: лише {_n(have)} шт по ≤ ${price:.2f} (треба {qty}) — чекаю ⏳")
            if fp is not None:
                lines.append(f"Набрати {qty} шт зараз: від <b>${fp:.2f}</b>")
    else:
        lines.append(f"Ціль: ціна {sg} <b>${price:.2f}</b>"
                     + ("  (чекаю зростання)" if direction == "up" else ""))
        if best is not None:
            _, lbl, q = best
            if alerts.hit(price, q.price, direction):
                lines.append(f"Зараз: <b>${q.price:.2f}</b> ({lbl}) — вже {sg} цілі ✅")
                lines.append("<i>Сповіщу, коли умова знову перестане й почне виконуватись.</i>")
            else:
                d = abs(q.price - price)
                arrow = "+" if direction == "up" else "−"
                lines.append(f"Зараз: <b>${q.price:.2f}</b> ({lbl}) — ще {arrow}${d:.2f} до цілі ⏳")
        else:
            lines.append("Ціна зʼявиться після наступного оновлення.")
            asyncio.create_task(_kick_depth(depth))

    mkt = _mkt_line(canonical, market)
    if mkt:
        lines.append("")
        lines.append("Ринки: " + mkt)
    return "\n".join(lines), keyboards.after_add_kb(wid)


async def _kick_depth(depth):
    try:
        names = await db.watched_names()
        if names:
            await depth.refresh(names)
    except Exception:
        log.exception("ad-hoc depth refresh failed")


# ---------- команди ----------

@router.message(Command("start"))
async def cmd_start(message: Message):
    await message.answer(HELP, reply_markup=keyboards.MAIN_KB)
    await message.answer(_menu_text(), reply_markup=keyboards.menu_kb())


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(HELP, reply_markup=keyboards.menu_kb())


@router.message(Command("add"))
async def cmd_add(message: Message):
    await message.answer(_ADD_PROMPT, reply_markup=keyboards.add_kb())


@router.message(Command("undo"))
async def cmd_undo(message: Message, market):
    uid = message.from_user.id
    d = _last_deleted.pop(uid, None)
    if not d:
        await message.answer("Нема що повертати.", reply_markup=keyboards.back_kb())
        return
    await db.add_watch(uid, message.chat.id, d["skin_name"], d["target_price"],
                       min_qty=d["min_qty"], direction=d["direction"])
    text, kb = await _list_view(uid, market)
    await message.answer("↩️ Повернув: " + _esc(d["skin_name"]) + "\n\n" + text,
                         reply_markup=kb)


@router.message(Command("menu"))
async def cmd_menu(message: Message):
    await message.answer(_menu_text(), reply_markup=keyboards.menu_kb())


@router.message(Command("whoami"))
async def cmd_whoami(message: Message):
    await message.answer(f"твій Telegram id: {message.from_user.id}",
                         reply_markup=keyboards.back_kb())


@router.message(Command("list"))
async def cmd_list(message: Message, market):
    text, kb = await _list_view(message.from_user.id, market)
    await message.answer(text, reply_markup=kb)


@router.message(Command("status"))
async def cmd_status(message: Message, client, depth, market):
    text, kb = await _status_view(market, client, depth)
    await message.answer(text, reply_markup=kb)


@router.message(Command("top"))
async def cmd_top(message: Message, market):
    text, kb = await _top_view(message.from_user.id, market, "cheap")
    await message.answer(text, reply_markup=kb)


@router.message(Command("depth"))
async def cmd_depth(message: Message, command: CommandObject, client, depth, market):
    try:
        wid = int((command.args or "").strip())
    except ValueError:
        await message.answer("Формат: /depth <id>", reply_markup=keyboards.back_kb())
        return
    text, kb = await _depth_view(message.from_user.id, wid, client, depth, market)
    await message.answer(text, reply_markup=kb)


@router.message(Command("compare"))
async def cmd_compare(message: Message, command: CommandObject, client, market):
    q = (command.args or "").strip()
    if not q:
        await message.answer("Формат: /compare <назва скіна>",
                             reply_markup=keyboards.menu_kb())
        return
    canonical, _ = matcher.resolve(q, client.names)
    name = canonical or q
    text, kb = await _compare_view(name, market)
    await message.answer(text, reply_markup=kb)


@router.message(Command("watch"))
async def cmd_watch(message: Message, command: CommandObject, client, depth, market):
    if not command.args:
        await message.answer(_ADD_PROMPT, reply_markup=keyboards.add_kb())
        return
    try:
        name, price, qty, direction = _parse_watch_args(command.args)
    except ValueError:
        await message.answer(_ADD_PROMPT, reply_markup=keyboards.add_kb())
        return
    text, kb = await _add_watch(message.from_user.id, message.chat.id,
                                name, price, qty, direction, client, depth, market)
    await message.answer(text, reply_markup=kb)


@router.message(Command("find"))
async def cmd_find(message: Message, command: CommandObject, client, market):
    q = (command.args or "").strip()
    if not q:
        await message.answer("Напиши назву або частину після /find.",
                             reply_markup=keyboards.menu_kb())
        return
    await _do_search(message, q, client, market)


@router.message(Command("unwatch"))
async def cmd_unwatch(message: Message, command: CommandObject):
    try:
        wid = int((command.args or "").strip())
    except ValueError:
        await message.answer("Формат: /unwatch <id>")
        return
    ok = await db.remove_watch(message.from_user.id, wid)
    await message.answer(f"Прибрав #{wid}." if ok else f"Немає #{wid}.")


@router.message(Command("mute"))
async def cmd_mute(message: Message, command: CommandObject):
    try:
        wid = int((command.args or "").strip())
    except ValueError:
        await message.answer("Формат: /mute <id>")
        return
    ok = await db.set_muted(message.from_user.id, wid, True)
    await message.answer(f"Стишив #{wid}." if ok else f"Немає #{wid}.")


@router.message(Command("unmute"))
async def cmd_unmute(message: Message, command: CommandObject):
    try:
        wid = int((command.args or "").strip())
    except ValueError:
        await message.answer("Формат: /unmute <id>")
        return
    ok = await db.set_muted(message.from_user.id, wid, False)
    await message.answer(f"Увімкнув #{wid}." if ok else f"Немає #{wid}.")


# ---------- нижня клавіатура ----------

@router.message(F.text == "📋 Список")
async def kb_list(message: Message, market):
    text, kb = await _list_view(message.from_user.id, market)
    await message.answer(text, reply_markup=kb)


@router.message(F.text == "➕ Додати")
async def kb_add(message: Message):
    await message.answer(_ADD_PROMPT, reply_markup=keyboards.add_kb())


@router.message(F.text == "🔎 Знайти")
async def kb_search(message: Message):
    await message.answer("Напиши назву скіна або частину — покажу варіанти.",
                         reply_markup=keyboards.menu_kb())


@router.message(F.text == "🔀 Порівняти")
async def kb_compare(message: Message):
    _pending_compare.add(message.from_user.id)
    await message.answer("Напиши назву скіна — покажу ціни на всіх ринках.",
                         reply_markup=keyboards.menu_kb())


@router.message(F.text == "❓ Довідка")
async def kb_help(message: Message):
    await message.answer(HELP, reply_markup=keyboards.menu_kb())


# ---------- вільний текст ----------

async def _do_search(message: Message, q: str, client, market):
    if not client.ready():
        await message.answer("Каталог ще вантажиться.")
        return
    hits = [n for n, s in matcher.best_matches(q, client.names, 10)
            if s > matcher.MIN_SUGGEST]
    if not hits:
        await message.answer("Нічого не знайшов.", reply_markup=keyboards.menu_kb())
        return
    _last_search[message.from_user.id] = hits
    items = [(n, market.best(n)[2].price if market.best(n) else None) for n in hits]
    await message.answer("Вибери скін:", reply_markup=keyboards.find_kb(items))


@router.message(F.text & ~F.text.startswith("/"))
async def on_text(message: Message, client, depth, market):
    txt = (message.text or "").strip()
    uid = message.from_user.id
    if not txt or len(txt) > 120:
        return

    # порівняти ціни на введеній назві
    if uid in _pending_compare:
        _pending_compare.discard(uid)
        canonical, _ = matcher.resolve(txt, client.names)
        text, kb = await _compare_view(canonical or txt, market)
        await message.answer(text, reply_markup=kb)
        return

    # нова ціль для стеження, що редагується
    if uid in _pending_edit:
        wid = _pending_edit.pop(uid)
        try:
            price, qty, direction = _parse_price_qty(txt)
        except ValueError:
            _pending_edit[uid] = wid
            await message.answer("Треба число, напр. 0.13 (або 0.13 x200, або 0.20 вгору)")
            return
        ok = await db.set_target(uid, wid, price, qty, direction)
        if not ok:
            await message.answer(f"Немає стеження #{wid}.")
            return
        text, kb = await _watch_card(uid, wid, market)
        await message.answer("Ціль оновлено.\n\n" + text, reply_markup=kb)
        return

    if uid in _pending_price:
        name = _pending_price.pop(uid)
        try:
            price, qty, direction = _parse_price_qty(txt)
        except ValueError:
            _pending_price[uid] = name
            await message.answer("Треба число, напр. 55 (або 0.44 x200, або 0.60 вгору)")
            return
        text, kb = await _add_watch(uid, message.chat.id, name, price, qty,
                                    direction, client, depth, market)
        await message.answer(text, reply_markup=kb)
        return

    try:
        name, price, qty, direction = _parse_watch_args(txt)
    except ValueError:
        name = None
    if name is not None:
        text, kb = await _add_watch(uid, message.chat.id, name, price, qty,
                                    direction, client, depth, market)
        await message.answer(text, reply_markup=kb)
        return

    await _do_search(message, txt, client, market)


# ---------- інлайн-кнопки ----------

@router.callback_query()
async def on_callback(cb: CallbackQuery, client, depth, market):
    if cb.message is None:
        await cb.answer()
        return
    data = cb.data or ""
    action, _, sid = data.partition(":")
    uid = cb.from_user.id

    # --- навігація (перемальовуємо на місці) ---
    if action == "menu":
        await _show(cb, _menu_text(), keyboards.menu_kb())
        return
    if action == "help":
        await _show(cb, HELP, keyboards.menu_kb())
        return
    if action == "status":
        await _show(cb, *await _status_view(market, client, depth))
        return
    if action == "top":
        mode = sid.split(":")[0]
        if mode not in ("cheap", "spread"):
            mode = "cheap"
        await _show(cb, *await _top_view(uid, market, mode))
        return
    if action == "lst":
        try:
            page = int(sid)
        except ValueError:
            page = 0
        await _show(cb, *await _list_view(uid, market, page))
        return
    if action == "srt":
        if sid in ("state", "price", "name"):
            _sort_mode[uid] = sid
        await _show(cb, *await _list_view(uid, market), toast=f"сорт: {sid}")
        return
    if action == "allmut":
        n = await db.mute_all(uid, True)
        await _show(cb, *await _list_view(uid, market), toast=f"стишено: {n}")
        return
    if action == "clrdone":
        n = await db.remove_triggered(uid)
        await _show(cb, *await _list_view(uid, market), toast=f"прибрано: {n}")
        return
    if action == "undo":
        d = _last_deleted.pop(uid, None)
        if d:
            await db.add_watch(uid, cb.message.chat.id, d["skin_name"],
                               d["target_price"], min_qty=d["min_qty"],
                               direction=d["direction"])
        await _show(cb, *await _list_view(uid, market),
                    toast="↩️ повернуто" if d else "нема що повертати")
        return

    # --- підказки (нове повідомлення, тут edit недоречний) ---
    if action == "add":
        await cb.message.answer(_ADD_PROMPT, reply_markup=keyboards.add_kb())
        await cb.answer()
        return
    if action == "find":
        await cb.message.answer("Напиши назву скіна або частину — покажу варіанти.")
        await cb.answer()
        return
    if action == "cmpask":
        _pending_compare.add(uid)
        await cb.message.answer("Напиши назву скіна — покажу ціни на всіх ринках.")
        await cb.answer()
        return
    if action == "pk":
        try:
            name = _last_search.get(uid, [])[int(sid)]
        except (ValueError, IndexError):
            await cb.answer("застаріло, повтори пошук")
            return
        _pending_price[uid] = name
        await _ask_price(cb, name, market)
        return
    if action == "qa":
        try:
            wanted = keyboards.QUICK_ADD[int(sid)]
        except (ValueError, IndexError):
            await cb.answer()
            return
        canonical, _ = matcher.resolve(wanted, client.names)
        if canonical is None:
            await cb.message.answer(f"«{_esc(wanted)}» зараз нема в каталозі lis-skins.")
            await cb.answer()
            return
        _pending_price[uid] = canonical
        await _ask_price(cb, canonical, market)
        return
    if action == "tp":
        try:
            name = _last_top.get(uid, [])[int(sid)]
        except (ValueError, IndexError):
            await cb.answer("застаріло")
            return
        canonical, _ = matcher.resolve(name, client.names)
        if canonical is None:
            await cb.message.answer(f"«{_esc(name)}» нема в каталозі lis-skins.")
            await cb.answer()
            return
        _pending_price[uid] = canonical
        await _ask_price(cb, canonical, market)
        return
    if action == "pp":
        name = _pending_price.pop(uid, None)
        if not name:
            await cb.answer("застаріло")
            return
        try:
            price = float(sid)
        except ValueError:
            await cb.answer()
            return
        text, kb = await _add_watch(uid, cb.message.chat.id, name, price, 1,
                                    "down", client, depth, market)
        await cb.message.answer(text, reply_markup=kb)
        await cb.answer()
        return

    # --- дії над стеженням #wid ---
    if action == "snz":
        parts = sid.split(":")
        try:
            wid = int(parts[0])
        except (ValueError, IndexError):
            await cb.answer()
            return
        if len(parts) == 1:
            await _show(cb, f"Тиша для #{wid}:", keyboards.snooze_kb(wid))
            return
        mins = int(parts[1])
        await db.snooze(uid, wid, mins)
        toast = f"тиша {mins // 60} год" if mins >= 60 else f"тиша {mins} хв"
        await _show(cb, *await _watch_card(uid, wid, market), toast=toast)
        return
    if action == "ok":
        try:
            await cb.message.edit_reply_markup(reply_markup=None)
        except Exception:
            pass
        await cb.answer("ок")
        return
    if action == "edp":
        try:
            wid, price = int(sid.split(":")[0]), float(sid.split(":")[1])
        except (ValueError, IndexError):
            await cb.answer()
            return
        _pending_edit.pop(uid, None)
        w = await db.get_watch(uid, wid)
        dr = w["direction"] if w else "down"
        ok = await db.set_target(uid, wid, price, 1, dr)
        await _show(cb, *await _watch_card(uid, wid, market),
                    toast="ціль оновлено" if ok else "нема такого")
        return

    try:
        wid = int(sid)
    except ValueError:
        await cb.answer()
        return

    if action == "w":
        w = await db.get_watch(uid, wid)
        await _show(cb, *await _watch_card(uid, wid, market))
        if w is not None:
            asyncio.create_task(_steam_followup(
                cb, w["skin_name"], market, lambda: _watch_card(uid, wid, market)))
        return
    if action == "dep":
        await _show(cb, *await _depth_view(uid, wid, client, depth, market))
        return
    if action == "cmp":
        w = await db.get_watch(uid, wid)
        if w is None:
            await cb.answer("нема такого")
            return
        nm = w["skin_name"]
        await _show(cb, *await _compare_view(nm, market))
        asyncio.create_task(_steam_followup(
            cb, nm, market, lambda: _compare_view(nm, market)))
        return
    if action == "ed":
        w = await db.get_watch(uid, wid)
        if w is None:
            await cb.answer("нема такого")
            return
        _pending_edit[uid] = wid
        await _ask_price(cb, w["skin_name"], market, edit_wid=wid,
                        direction=w["direction"])
        return
    if action == "del":
        w = await db.get_watch(uid, wid)
        if w is not None:
            _last_deleted[uid] = {
                "skin_name": w["skin_name"], "target_price": w["target_price"],
                "min_qty": w["min_qty"], "direction": w["direction"],
            }
        ok = await db.remove_watch(uid, wid)
        await _show(cb, *await _list_view(uid, market),
                    toast=f"#{wid} прибрано" if ok else "нема такого")
        return
    if action in ("mut", "unm"):
        await db.set_muted(uid, wid, action == "mut")
        await _show(cb, *await _watch_card(uid, wid, market),
                    toast="стишено" if action == "mut" else "увімкнено")
        return

    await cb.answer()
