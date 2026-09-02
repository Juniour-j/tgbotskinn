"""Команди, текст і кнопки Telegram-бота."""
from __future__ import annotations

import asyncio
import logging
import re

from aiogram import F, Router
from aiogram.filters import Command, CommandObject
from aiogram.types import CallbackQuery, Message

from . import db, keyboards, matcher

log = logging.getLogger("handlers")
router = Router()

HELP = (
    "Стежу за цінами скінів на lis-skins.com (CS2). Все через кнопки нижче.\n\n"
    "Додати стеження — просто напиши:\n"
    "  <назва> <ціна>            напр.  AWP | Asiimov (Field-Tested) 55\n"
    "  <назва> <ціна> x<шт>      напр.  Sealed Dead Hand Terminal 0.44 x200\n"
    "        (x<шт> — сповістити, коли можна КУПИТИ >= стільки лотів по <= ціна)\n\n"
    "Не знаєш точну назву — напиши частину, покажу варіанти кнопками.\n\n"
    "Ціна = як на сайті. Перевірка ~щохвилини, глибина — раз на ~10 хв."
)

_QTY_RE = re.compile(r"^[xхXХ*](\d+)$")

# короткочасний стан у памʼяті (втрачається при рестарті — не критично)
_pending_price: dict[int, str] = {}     # user_id -> canonical name, чекаємо ціну
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
    return "Меню. Що робимо?"


async def _list_view(user_id: int, client, depth):
    rows = await db.list_watches(user_id)
    if not rows:
        return "Порожньо — додай перше стеження.", keyboards.menu_kb()
    out = []
    for r in rows:
        state = " [muted]" if r["muted"] else (" [спрацював]" if r["triggered"] else "")
        name = r["skin_name"]
        item = client.lookup(name)
        sp = depth.site_price(name)
        if sp is not None:
            now = f"${sp:.2f}"
        elif item is not None:
            now = f"${item.price:.2f}~"
        elif r["last_price"] is not None:
            now = f"${r['last_price']:.2f}~"
        else:
            now = "?"
        if r["min_qty"] > 1:
            have = depth.buyable_qty(name, r["target_price"])
            have_s = f"{have} шт" if have is not None else "?"
            fp = depth.fill_price(name, r["min_qty"])
            fp_s = f", {r['min_qty']} шт від ${fp:.2f}" if fp is not None else ""
            tail = (f"зараз {now}; по <= ${r['target_price']:.2f}: {have_s} "
                    f"(треба x{r['min_qty']}){fp_s}")
        else:
            tail = f"зараз {now}, ціль <= ${r['target_price']:.2f}"
        out.append(f"#{r['id']}  {name}  —  {tail}{state}")
    return "\n".join(out), keyboards.list_kb(rows)


async def _depth_view(user_id: int, wid: int, client, depth):
    w = await db.get_watch(user_id, wid)
    if w is None:
        return f"Немає стеження #{wid}.", keyboards.back_kb()
    name = w["skin_name"]
    if not depth.has(name):
        asyncio.create_task(_kick_depth(depth))
        return (f"Глибина для «{name}» ще не завантажена.\n"
                "Оновлюється раз на ~10 хв. Спробуй за хвилину."), keyboards.depth_kb(wid)
    sp = depth.site_price(name)
    rungs = depth.ladder(name, 12, from_price=sp)
    out = [name]
    if sp is not None:
        out.append(f"ціна на сайті: ${sp:.2f}")
    out += [f"глибина оновлена {depth.age_min()} хв тому", "", "ціна    шт     сумарно"]
    cum = 0
    for p, q in rungs:
        cum += q
        out.append(f"${p:<6.2f} {q:<6} {cum}")
    q_want = w["min_qty"] if w["min_qty"] > 1 else 50
    fill = depth.fill_price(name, q_want)
    have = depth.buyable_qty(name, w["target_price"])
    out.append("")
    if fill is not None:
        out.append(f"{q_want} шт набрати від: ${fill:.2f}")
    out.append(f"по <= ${w['target_price']:.2f}: {have} шт (ціль x{w['min_qty']})")
    return "\n".join(out), keyboards.depth_kb(wid)


async def _add_watch(uid: int, chat_id: int, raw_name: str, price: float,
                     qty: int, client, depth):
    canonical, exact = matcher.resolve(raw_name, client.names)
    if canonical is None:
        sugg = [n for n, s in matcher.best_matches(raw_name, client.names, 8)
                if s > matcher.MIN_SUGGEST]
        _last_search[uid] = sugg
        if sugg:
            return (f"«{raw_name}» — не впевнений. Вибери:", keyboards.find_kb(sugg))
        return (f"Не знайшов «{raw_name}». Напиши інакше.", keyboards.menu_kb())

    wid, action = await db.add_watch(uid, chat_id, canonical, price, min_qty=qty)
    if wid is None:
        return "Не вдалося зберегти.", keyboards.menu_kb()

    verb = "Стежу" if action == "created" else "Оновив"
    lines = [f"{verb} [#{wid}]: {canonical}", f"Ціль: <= ${price:.2f}"]
    sp = depth.site_price(canonical)
    if sp is not None:
        lines.append(f"Ціна зараз: ${sp:.2f}")
    else:
        item = client.lookup(canonical)
        if item is not None:
            lines.append(f"Ціна зараз: ${item.price:.2f} (уточниться за хвилину)")
        asyncio.create_task(_kick_depth(depth))
    if qty > 1:
        have = depth.buyable_qty(canonical, price)
        if have is not None:
            fp = depth.fill_price(canonical, qty)
            fp_s = f", {qty} шт від ${fp:.2f}" if fp is not None else ""
            lines.append(f"Зараз по <= ${price:.2f}: {have} шт (треба x{qty}){fp_s}")
        else:
            lines.append(f"Треба >= {qty} шт (глибина зʼявиться за хвилину)")
            asyncio.create_task(_kick_depth(depth))
    if not exact:
        lines.append("(підібрав за схожістю)")
    return "\n".join(lines), keyboards.after_add_kb(wid)


async def _kick_depth(depth):
    try:
        names = await db.watched_names()
        if names:
            await depth.refresh(names)
    except Exception:
        log.exception("ad-hoc depth refresh failed")


_ADD_PROMPT = (
    "Надішли одним рядком:\n"
    "  <назва> <ціна>            або\n"
    "  <назва> <ціна> x<шт>\n\n"
    "Приклади:\n"
    "  AWP | Asiimov (Field-Tested) 55\n"
    "  Kilowatt Case 0.13 x200\n\n"
    "Не знаєш точну назву — просто напиши частину."
)


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
async def cmd_list(message: Message, client, depth):
    text, kb = await _list_view(message.from_user.id, client, depth)
    await message.answer(text, reply_markup=kb)


@router.message(Command("depth"))
async def cmd_depth(message: Message, command: CommandObject, client, depth):
    try:
        wid = int((command.args or "").strip())
    except ValueError:
        await message.answer("Формат: /depth <id>", reply_markup=keyboards.back_kb())
        return
    text, kb = await _depth_view(message.from_user.id, wid, client, depth)
    await message.answer(text, reply_markup=kb)


@router.message(Command("watch"))
async def cmd_watch(message: Message, command: CommandObject, client, depth):
    if not command.args:
        await message.answer(_ADD_PROMPT, reply_markup=keyboards.menu_kb())
        return
    try:
        name, price, qty = _parse_watch_args(command.args)
    except ValueError:
        await message.answer(_ADD_PROMPT, reply_markup=keyboards.menu_kb())
        return
    text, kb = await _add_watch(message.from_user.id, message.chat.id,
                                name, price, qty, client, depth)
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
async def kb_list(message: Message, client, depth):
    text, kb = await _list_view(message.from_user.id, client, depth)
    await message.answer(text, reply_markup=kb)


@router.message(F.text == "➕ Додати")
async def kb_add(message: Message):
    await message.answer(_ADD_PROMPT, reply_markup=keyboards.menu_kb())


@router.message(F.text == "🔎 Пошук")
async def kb_search(message: Message):
    await message.answer("Напиши назву скіна або частину — покажу варіанти.",
                         reply_markup=keyboards.menu_kb())


@router.message(F.text == "❓ Довідка")
async def kb_help(message: Message):
    await message.answer(HELP, reply_markup=keyboards.menu_kb())


# ---------- вільний текст: ціна / «назва ціна» / пошук ----------

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
async def on_text(message: Message, client, depth):
    txt = (message.text or "").strip()
    uid = message.from_user.id
    if not txt or len(txt) > 120:
        return

    # 1) чекаємо ціну для вибраного скіна
    if uid in _pending_price:
        name = _pending_price.pop(uid)
        try:
            price, qty = _parse_price_qty(txt)
        except ValueError:
            _pending_price[uid] = name
            await message.answer("Треба число, напр. 55 або 0.44 x200")
            return
        text, kb = await _add_watch(uid, message.chat.id, name, price, qty, client, depth)
        await message.answer(text, reply_markup=kb)
        return

    # 2) схоже на «<назва> <ціна> [x<шт>]»
    try:
        name, price, qty = _parse_watch_args(txt)
    except ValueError:
        name = None
    if name is not None:
        text, kb = await _add_watch(uid, message.chat.id, name, price, qty, client, depth)
        await message.answer(text, reply_markup=kb)
        return

    # 3) інакше — пошук
    await _do_search(message, txt, client)


# ---------- інлайн-кнопки ----------

@router.callback_query()
async def on_callback(cb: CallbackQuery, client, depth):
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
        await cb.message.answer(_ADD_PROMPT, reply_markup=keyboards.menu_kb())
        await cb.answer()
        return

    if action == "find":
        await cb.message.answer("Напиши назву скіна або частину — покажу варіанти.")
        await cb.answer()
        return

    if action == "lst":
        text, kb = await _list_view(uid, client, depth)
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
            f"«{name}»\nНадішли ціну: напр. 55 або 0.44 x200"
        )
        await cb.answer()
        return

    try:
        wid = int(sid)
    except ValueError:
        await cb.answer()
        return

    if action == "dep":
        text, kb = await _depth_view(uid, wid, client, depth)
        await cb.message.answer(text, reply_markup=kb)
        await cb.answer()
        return

    if action == "del":
        ok = await db.remove_watch(uid, wid)
        note = "прибрано" if ok else "нема такого"
    elif action == "mut":
        ok = await db.set_muted(uid, wid, True)
        note = "стишено" if ok else "нема такого"
    elif action == "unm":
        ok = await db.set_muted(uid, wid, False)
        note = "увімкнено" if ok else "нема такого"
    else:
        await cb.answer()
        return

    text, kb = await _list_view(uid, client, depth)
    try:
        await cb.message.edit_text(text, reply_markup=kb)
    except Exception:
        await cb.message.answer(text, reply_markup=kb)
    await cb.answer(f"#{wid} {note}")
