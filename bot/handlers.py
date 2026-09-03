"""Команди, текст і кнопки Telegram-бота."""
from __future__ import annotations

import asyncio
import html
import logging
import re

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from . import db, keyboards, matcher

log = logging.getLogger("handlers")
router = Router()

HELP = (
    "<b>Що я вмію</b>\n"
    "Слідкую за цінами скінів CS2 і пишу, коли ціна впаде до потрібної.\n"
    "Порівнюю 3 ринки — <b>lis-skins</b>, <b>market.csgo</b>, <b>Skinport</b> — і беру найдешевший.\n\n"
    "<b>Як додати</b>\n"
    "Напиши одним рядком назву й ціль у $:\n"
    "<code>Kilowatt Case 0.13</code>\n"
    "<code>AWP | Asiimov (Field-Tested) 55</code>\n"
    "→ сповіщу, щойно будь-де стане ≤ цієї ціни.\n\n"
    "<b>Стеження за обсягом</b> — додай <code>x&lt;кількість&gt;</code>:\n"
    "<code>Kilowatt Case 0.13 x200</code>\n"
    "→ сповіщу, коли на lis-skins можна <b>купити</b> 200+ шт по ≤ $0.13.\n\n"
    "Не знаєш точну назву — напиши частину («kilowatt»), покажу варіанти кнопками.\n\n"
    "У списку під кожним стеженням: <b>📊 Глибина</b> і <b>⚙️ Керувати</b>\n"
    "(там: 🔗 відкрити, ✏️ змінити ціль, 🔀 порівняти, 🔕 звук, 🗑 видалити)."
)

_ADD_PROMPT = (
    "<b>Напиши назву скіна і ціль у $</b> одним рядком:\n\n"
    "<code>Kilowatt Case 0.13</code>\n"
    "   → сповіщу, коли ціна впаде до $0.13\n\n"
    "<code>Kilowatt Case 0.13 x200</code>\n"
    "   → сповіщу, коли можна купити 200+ шт по ≤ $0.13\n\n"
    "Не знаєш точну назву — напиши частину, покажу варіанти.\n"
    "Або обери популярний кейс кнопкою ⬇️"
)

_QTY_RE = re.compile(r"^[xхXХ*](\d+)$")

# короткочасний стан у памʼяті (втрачається при рестарті — не критично)
_pending_price: dict[int, str] = {}     # user_id -> canonical name, чекаємо ціну
_pending_edit: dict[int, int] = {}      # user_id -> watch_id, чекаємо нову ціль
_pending_compare: set[int] = set()      # user_id -> чекаємо назву для /compare
_last_search: dict[int, list] = {}      # user_id -> список знайдених назв


# ---------- парсери ----------

def _parse_watch_args(args: str):
    toks = args.split()
    if len(toks) < 2:
        raise ValueError
    qty = 1
    m = _QTY_RE.match(toks[-1])
    if m and len(toks) >= 3:
        qty = int(m.group(1))
        toks.pop()
    price = float(toks[-1].strip().lstrip("$").replace(",", "."))
    toks.pop()
    name = " ".join(toks).strip()
    if not name or price <= 0 or qty < 1:
        raise ValueError
    return name, price, qty


def _parse_price_qty(s: str):
    toks = s.split()
    qty = 1
    m = _QTY_RE.match(toks[-1]) if toks else None
    if m and len(toks) >= 2:
        qty = int(m.group(1))
        toks.pop()
    if len(toks) != 1:
        raise ValueError
    price = float(toks[0].strip().lstrip("$").replace(",", "."))
    if price <= 0 or qty < 1:
        raise ValueError
    return price, qty


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


def _mkt_line(name: str, market, short: bool = False) -> str:
    qs = sorted(market.quotes(name), key=lambda t: t[2].price)
    return "  ·  ".join(
        f"{(_SHORT.get(lbl, lbl) if short else lbl)} <b>${q.price:.2f}</b>"
        for _, lbl, q in qs
    )


def _state(row, met: bool) -> str:
    if row["muted"]:
        return "🔕 без звуку"
    if met:
        return "✅ ціль досягнута" + (" · сповіщено" if row["triggered"] else "")
    return "⏳ чекаю"


def _icon(row, met: bool) -> str:
    return "🔕" if row["muted"] else ("✅" if met else "⏳")


async def _list_view(user_id: int, market):
    rows = await db.list_watches(user_id)
    if not rows:
        return ("<b>Ще нема жодного стеження.</b>\n\n"
                "Тисни ➕ Додати або просто напиши «назва ціна»:\n"
                "<code>Kilowatt Case 0.13</code>"), keyboards.add_kb()
    depth = market.depth
    done = 0
    blocks = []
    for r in rows:
        name = _esc(r["skin_name"])
        t = r["target_price"]
        mkt = _mkt_line(r["skin_name"], market, short=True) or "ціни ще нема"
        if r["min_qty"] > 1:
            have = depth.buyable_qty(r["skin_name"], t)
            met = have is not None and have >= r["min_qty"]
            fp = depth.fill_price(r["skin_name"], r["min_qty"])
            now = f"{_n(have)} шт" if have is not None else "…"
            extra = f"\nнабрати {r['min_qty']} шт: від <b>${fp:.2f}</b>" if fp else ""
            blocks.append(
                f"{_icon(r, met)} <b>#{r['id']} {name}</b> · опт ≥{r['min_qty']}\n"
                f"ціль ≤ ${t:.2f} · зараз {now} по ≤ ${t:.2f}{extra}\n"
                f"{mkt}"
            )
        else:
            best = market.best(r["skin_name"])
            met = best is not None and best[2].price <= t
            if best is not None:
                gap = best[2].price - t
                tail = ("вже нижче цілі" if gap <= 0
                        else f"ще −${gap:.2f} до цілі")
                now = f"<b>${best[2].price:.2f}</b> ({_SHORT.get(best[1], best[1])}) · {tail}"
            else:
                now = "?"
            blocks.append(
                f"{_icon(r, met)} <b>#{r['id']} {name}</b>\n"
                f"ціль ≤ ${t:.2f} · зараз {now}\n"
                f"{mkt}"
            )
        if met and not r["muted"]:
            done += 1
    hdr = f"<b>📋 Стеження: {len(rows)}</b>"
    if done:
        hdr += f"  ·  ✅ {done}"
    return hdr + "\n\n" + "\n\n".join(blocks), keyboards.list_kb(rows)


def _open_links(name: str, market):
    out = []
    for _, lbl, q in sorted(market.quotes(name), key=lambda t: t[2].price):
        if q.url:
            out.append((lbl, q.url))
    return out


async def _watch_card(user_id: int, wid: int, market):
    w = await db.get_watch(user_id, wid)
    if w is None:
        return f"Немає стеження #{wid}.", keyboards.back_kb()
    name, t, depth = w["skin_name"], w["target_price"], market.depth
    best = market.best(name)
    lines = [f"<b>#{wid} · {_esc(name)}</b>", ""]
    if w["min_qty"] > 1:
        have = depth.buyable_qty(name, t)
        met = have is not None and have >= w["min_qty"]
        lines.append(f"Ціль:  ≥ {w['min_qty']} шт по ≤ <b>${t:.2f}</b>  (lis-skins)")
        lines.append(f"Стан:  {_state(w, met)}")
        if have is not None:
            lines.append(f"Зараз: {_n(have)} шт по ≤ ${t:.2f}")
        fp = depth.fill_price(name, w["min_qty"])
        if fp is not None:
            lines.append(f"Набрати {w['min_qty']} шт: від <b>${fp:.2f}</b>")
    else:
        met = best is not None and best[2].price <= t
        lines.append(f"Ціль:  ≤ <b>${t:.2f}</b>")
        lines.append(f"Стан:  {_state(w, met)}")
        if best is not None:
            gap = best[2].price - t
            note = "" if gap <= 0 else f"  (ще −${gap:.2f})"
            lines.append(f"Зараз: <b>${best[2].price:.2f}</b> — {best[1]}{note}")
    qs = sorted(market.quotes(name), key=lambda x: x[2].price)
    if qs:
        lines.append("")
        lines.append("Ціни по ринках:")
        rows = [f"{'▸ ' if i == 0 else '  '}{lbl:<12}{'$' + format(q.price, '.2f'):>8}"
                for i, (_, lbl, q) in enumerate(qs)]
        lines.append("<pre>" + _esc("\n".join(rows)) + "</pre>")
    return ("\n".join(lines),
            keyboards.watch_kb(wid, bool(w["muted"]), _open_links(name, market)))


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
    out = [f"<b>📊 {_esc(name)}</b> · lis-skins"]
    if sp is not None:
        out.append(f"ціна на сайті <b>${sp:.2f}</b> · оновлено {depth.age_min()} хв тому")
    body = [f"{'ціна':<7}{'шт':>8}   {'сумарно':>9}"]
    cum = 0
    for p, q in rungs:
        cum += q
        body.append(f"${p:<6.2f}{_n(q):>8}   {_n(cum):>9}  {_bar(q, mx)}")
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
    rows = [f"{'▸ ' if i == 0 else '  '}{lbl:<12}{'$' + format(q.price, '.2f'):>8}"
            + (f"   {_n(q.qty)} шт" if q.qty else "")
            for i, (_, lbl, q) in enumerate(qs)]
    out = [f"<b>🔀 {_esc(name)}</b>", "ціни зараз:", "",
           "<pre>" + _esc("\n".join(rows)) + "</pre>"]
    if len(qs) > 1:
        lo, hi = qs[0][2].price, qs[-1][2].price
        pct = (hi - lo) / hi * 100 if hi else 0
        out.append(f"розкид ${hi - lo:.2f} — найдешевше на {pct:.0f}% нижче за найдорожче")
    return "\n".join(out), keyboards.back_kb()


async def _add_watch(uid: int, chat_id: int, raw_name: str, price: float,
                     qty: int, client, depth, market):
    canonical, exact = matcher.resolve(raw_name, client.names)
    if canonical is None:
        sugg = [n for n, s in matcher.best_matches(raw_name, client.names, 8)
                if s > matcher.MIN_SUGGEST]
        _last_search[uid] = sugg
        if sugg:
            return (f"«{_esc(raw_name)}» — не впевнений. Вибери:", keyboards.find_kb(sugg))
        return (f"Не знайшов «{_esc(raw_name)}». Напиши інакше.", keyboards.menu_kb())

    wid, action = await db.add_watch(uid, chat_id, canonical, price, min_qty=qty)
    if wid is None:
        return "Не вдалося зберегти. Спробуй ще раз.", keyboards.menu_kb()

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
        lines.append(f"Ціль: ціна ≤ <b>${price:.2f}</b>")
        if best is not None:
            _, lbl, q = best
            if q.price <= price:
                lines.append(f"Зараз: <b>${q.price:.2f}</b> ({lbl}) — вже ≤ цілі ✅")
                lines.append("<i>Сповіщу, якщо підніметься і знову впаде.</i>")
            else:
                lines.append(f"Зараз: <b>${q.price:.2f}</b> ({lbl}) — ще −${q.price - price:.2f} до цілі ⏳")
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
        name, price, qty = _parse_watch_args(command.args)
    except ValueError:
        await message.answer(_ADD_PROMPT, reply_markup=keyboards.add_kb())
        return
    text, kb = await _add_watch(message.from_user.id, message.chat.id,
                                name, price, qty, client, depth, market)
    await message.answer(text, reply_markup=kb)


@router.message(Command("find"))
async def cmd_find(message: Message, command: CommandObject, client):
    q = (command.args or "").strip()
    if not q:
        await message.answer("Напиши назву або частину після /find.",
                             reply_markup=keyboards.menu_kb())
        return
    await _do_search(message, q, client)


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

async def _do_search(message: Message, q: str, client):
    if not client.ready():
        await message.answer("Каталог ще вантажиться.")
        return
    hits = [n for n, s in matcher.best_matches(q, client.names, 10)
            if s > matcher.MIN_SUGGEST]
    if not hits:
        await message.answer("Нічого не знайшов.", reply_markup=keyboards.menu_kb())
        return
    _last_search[message.from_user.id] = hits
    await message.answer("Вибери скін:", reply_markup=keyboards.find_kb(hits))


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
            price, qty = _parse_price_qty(txt)
        except ValueError:
            _pending_edit[uid] = wid
            await message.answer("Треба число, напр. 0.13 або 0.13 x200")
            return
        ok = await db.set_target(uid, wid, price, qty)
        if not ok:
            await message.answer(f"Немає стеження #{wid}.")
            return
        text, kb = await _watch_card(uid, wid, market)
        await message.answer("Ціль оновлено.\n\n" + text, reply_markup=kb)
        return

    if uid in _pending_price:
        name = _pending_price.pop(uid)
        try:
            price, qty = _parse_price_qty(txt)
        except ValueError:
            _pending_price[uid] = name
            await message.answer("Треба число, напр. 55 або 0.44 x200")
            return
        text, kb = await _add_watch(uid, message.chat.id, name, price, qty,
                                    client, depth, market)
        await message.answer(text, reply_markup=kb)
        return

    try:
        name, price, qty = _parse_watch_args(txt)
    except ValueError:
        name = None
    if name is not None:
        text, kb = await _add_watch(uid, message.chat.id, name, price, qty,
                                    client, depth, market)
        await message.answer(text, reply_markup=kb)
        return

    await _do_search(message, txt, client)


# ---------- інлайн-кнопки ----------

@router.callback_query()
async def on_callback(cb: CallbackQuery, client, depth, market):
    if cb.message is None:
        await cb.answer()
        return
    data = cb.data or ""
    action, _, sid = data.partition(":")
    uid = cb.from_user.id

    if action == "menu":
        await cb.message.answer(_menu_text(), reply_markup=keyboards.menu_kb())
        await cb.answer()
        return
    if action == "help":
        await cb.message.answer(HELP, reply_markup=keyboards.menu_kb())
        await cb.answer()
        return
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
    if action == "lst":
        text, kb = await _list_view(uid, market)
        await cb.message.answer(text, reply_markup=kb)
        await cb.answer()
        return
    if action == "pk":
        try:
            idx = int(sid)
            name = _last_search.get(uid, [])[idx]
        except (ValueError, IndexError):
            await cb.answer("застаріло, повтори пошук")
            return
        _pending_price[uid] = name
        await cb.message.answer(
            f"«{_esc(name)}»\nТепер напиши ціль у $ — напр. <code>0.13</code>\n"
            "(або <code>0.13 x200</code>, щоб чекати опт)")
        await cb.answer()
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
        await cb.message.answer(
            f"«{_esc(canonical)}»\nТепер напиши ціль у $ — напр. <code>0.13</code>\n"
            "(або <code>0.13 x200</code>, щоб чекати опт)")
        await cb.answer()
        return

    try:
        wid = int(sid)
    except ValueError:
        await cb.answer()
        return

    if action == "w":
        text, kb = await _watch_card(uid, wid, market)
        await cb.message.answer(text, reply_markup=kb)
        await cb.answer()
        return
    if action == "dep":
        text, kb = await _depth_view(uid, wid, client, depth, market)
        await cb.message.answer(text, reply_markup=kb)
        await cb.answer()
        return
    if action == "cmp":
        w = await db.get_watch(uid, wid)
        if w is None:
            await cb.answer("нема такого")
            return
        text, kb = await _compare_view(w["skin_name"], market)
        await cb.message.answer(text, reply_markup=kb)
        await cb.answer()
        return
    if action == "ed":
        w = await db.get_watch(uid, wid)
        if w is None:
            await cb.answer("нема такого")
            return
        _pending_edit[uid] = wid
        await cb.message.answer(
            f"<b>#{wid} · {_esc(w['skin_name'])}</b>\n"
            "Надішли нову ціль у $ — напр. <code>0.13</code>\n"
            "(або <code>0.13 x200</code> для стеження за обсягом)")
        await cb.answer()
        return

    if action == "del":
        ok = await db.remove_watch(uid, wid)
        text, kb = await _list_view(uid, market)
        try:
            await cb.message.edit_text(text, reply_markup=kb)
        except Exception:
            await cb.message.answer(text, reply_markup=kb)
        await cb.answer(f"#{wid} прибрано" if ok else "нема такого")
        return
    if action in ("mut", "unm"):
        await db.set_muted(uid, wid, action == "mut")
        text, kb = await _watch_card(uid, wid, market)
        try:
            await cb.message.edit_text(text, reply_markup=kb)
        except Exception:
            await cb.message.answer(text, reply_markup=kb)
        await cb.answer("стишено" if action == "mut" else "увімкнено")
        return

    await cb.answer()
