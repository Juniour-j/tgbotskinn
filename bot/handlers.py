"""Команди й кнопки Telegram-бота."""
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
    "Стежу за цінами скінів на lis-skins.com (CS2).\n\n"
    "/watch <назва> <ціна> — стежити за ціною\n"
    "    напр.: /watch AWP | Asiimov (Field-Tested) 55\n"
    "/watch <назва> <ціна> x<шт> — стежити за ОБСЯГОМ:\n"
    "    спрацює, коли можна купити >= <шт> лотів по ціні <= <ціна>\n"
    "    напр.: /watch Sealed Dead Hand Terminal 0.44 x200\n"
    "/depth <id> — драбина цін (скільки лотів по якій ціні)\n"
    "/find <текст> — знайти точну назву скіна\n"
    "/list — мої стеження (з кнопками)\n"
    "/unwatch <id> · /mute <id> · /unmute <id>\n"
    "/whoami — мій Telegram id\n\n"
    "Ціна = як на сайті. Перевірка ~щохвилини, глибина — раз на ~10 хв.\n"
    "Сповіщення приходить один раз; знову спрацює, якщо умова знову перестане й почне виконуватись."
)

_QTY_RE = re.compile(r"^[xхXХ*](\d+)$")


# ---------- спільні білдери ----------

async def _list_view(user_id: int, client, depth):
    rows = await db.list_watches(user_id)
    if not rows:
        return "Порожньо. Додай через /watch.", None
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
        return f"Немає стеження #{wid}.", None
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


@router.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(HELP)


@router.message(Command("whoami"))
async def cmd_whoami(message: Message):
    await message.answer(f"твій Telegram id: {message.from_user.id}")


def _parse_watch_args(args: str) -> tuple[str, float, int]:
    toks = args.split()
    if len(toks) < 2:
        raise ValueError("too few tokens")
    qty = 1
    m = _QTY_RE.match(toks[-1])
    if m and len(toks) >= 3:
        qty = int(m.group(1))
        toks.pop()
    price = float(toks[-1].strip().lstrip("$").replace(",", "."))
    toks.pop()
    name = " ".join(toks).strip()
    if not name or price <= 0 or qty < 1:
        raise ValueError("bad values")
    return name, price, qty


@router.message(Command("watch"))
async def cmd_watch(message: Message, command: CommandObject, client, depth):
    if not client.ready():
        await message.answer("Каталог ще вантажиться, спробуй за хвилину.")
        return
    if not command.args:
        await message.answer("Формат: /watch <назва> <ціна> [x<шт>]")
        return
    try:
        name, price, qty = _parse_watch_args(command.args)
    except ValueError:
        await message.answer(
            "Формат: /watch <назва> <ціна> [x<шт>]\n"
            "напр.: /watch AWP | Asiimov (Field-Tested) 55\n"
            "       /watch Sealed Dead Hand Terminal 0.44 x200"
        )
        return

    canonical, exact = matcher.resolve(name, client.names)
    if canonical is None:
        sugg = [n for n, s in matcher.best_matches(name, client.names, 5)
                if s > matcher.MIN_SUGGEST]
        if sugg:
            await message.answer(
                f"Не знайшов «{name}». Можливо:\n" + "\n".join(sugg)
                + "\n\nСкопіюй точну назву й повтори."
            )
        else:
            await message.answer(f"Не знайшов «{name}». Спробуй /find <текст>.")
        return

    item = client.lookup(canonical)
    wid, action = await db.add_watch(
        message.from_user.id, message.chat.id, canonical, price, min_qty=qty
    )
    if wid is None:
        await message.answer("Не вдалося зберегти стеження.")
        return

    verb = "Стежу" if action == "created" else "Оновив"
    lines = [f"{verb} [#{wid}]: {canonical}", f"Ціль: <= ${price:.2f}"]

    sp = depth.site_price(canonical)
    if sp is not None:
        lines.append(f"Ціна зараз: ${sp:.2f}")
    elif item is not None:
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
    await message.answer("\n".join(lines))


@router.message(Command("depth"))
async def cmd_depth(message: Message, command: CommandObject, client, depth):
    try:
        wid = int((command.args or "").strip())
    except ValueError:
        await message.answer("Формат: /depth <id> (id з /list)")
        return
    text, kb = await _depth_view(message.from_user.id, wid, client, depth)
    await message.answer(text, reply_markup=kb)


@router.message(Command("find"))
async def cmd_find(message: Message, command: CommandObject, client):
    if not client.ready():
        await message.answer("Каталог ще вантажиться.")
        return
    q = (command.args or "").strip()
    if not q:
        await message.answer("Формат: /find <текст>")
        return
    hits = [n for n, s in matcher.best_matches(q, client.names, 10)
            if s > matcher.MIN_SUGGEST]
    await message.answer("\n".join(hits) if hits else "Нічого не знайшов.")


@router.message(Command("list"))
async def cmd_list(message: Message, client, depth):
    text, kb = await _list_view(message.from_user.id, client, depth)
    await message.answer(text, reply_markup=kb)


def _parse_id(args: str | None) -> int:
    return int((args or "").strip())


@router.message(Command("unwatch"))
async def cmd_unwatch(message: Message, command: CommandObject):
    try:
        wid = _parse_id(command.args)
    except ValueError:
        await message.answer("Формат: /unwatch <id>")
        return
    ok = await db.remove_watch(message.from_user.id, wid)
    await message.answer(f"Прибрав #{wid}." if ok else f"Немає стеження #{wid}.")


@router.message(Command("mute"))
async def cmd_mute(message: Message, command: CommandObject):
    try:
        wid = _parse_id(command.args)
    except ValueError:
        await message.answer("Формат: /mute <id>")
        return
    ok = await db.set_muted(message.from_user.id, wid, True)
    await message.answer(f"Стишив #{wid}." if ok else f"Немає стеження #{wid}.")


@router.message(Command("unmute"))
async def cmd_unmute(message: Message, command: CommandObject):
    try:
        wid = _parse_id(command.args)
    except ValueError:
        await message.answer("Формат: /unmute <id>")
        return
    ok = await db.set_muted(message.from_user.id, wid, False)
    await message.answer(f"Увімкнув #{wid}." if ok else f"Немає стеження #{wid}.")


# ---------- нижня клавіатура ----------

@router.message(F.text == "📋 Список")
async def kb_list(message: Message, client, depth):
    text, kb = await _list_view(message.from_user.id, client, depth)
    await message.answer(text, reply_markup=kb)


@router.message(F.text == "❓ Довідка")
async def kb_help(message: Message):
    await message.answer(HELP)


# ---------- інлайн-кнопки ----------

@router.callback_query()
async def on_callback(cb: CallbackQuery, client, depth):
    if cb.message is None:
        await cb.answer()
        return
    data = cb.data or ""
    action, _, sid = data.partition(":")
    try:
        wid = int(sid)
    except ValueError:
        await cb.answer()
        return
    uid = cb.from_user.id

    if action == "lst":
        text, kb = await _list_view(uid, client, depth)
        await cb.message.answer(text, reply_markup=kb)
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
