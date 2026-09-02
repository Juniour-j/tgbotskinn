"""Команди Telegram-бота."""
from __future__ import annotations

import logging

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from . import db, matcher

log = logging.getLogger("handlers")
router = Router()

HELP = (
    "Стежу за цінами скінів на lis-skins.com (CS2).\n\n"
    "/watch <назва> <ціна> — почати стежити\n"
    "    напр.: /watch AWP | Asiimov (Field-Tested) 55\n"
    "/find <текст> — знайти точну назву скіна\n"
    "/list — мої стеження\n"
    "/unwatch <id> — прибрати стеження\n"
    "/mute <id> | /unmute <id> — вимкнути / увімкнути сповіщення\n\n"
    "Ціни в доларах. Перевірка кожні ~60 секунд.\n"
    "Сповіщення приходить один раз; знову спрацює, якщо ціна підніметься вище цілі й потім знову впаде."
)


@router.message(Command("start", "help"))
async def cmd_help(message: Message):
    await message.answer(HELP)


def _parse_name_price(args: str) -> tuple[str, float]:
    name, _, price_s = args.rpartition(" ")
    name = name.strip()
    if not name:
        raise ValueError("no name")
    price = float(price_s.strip().lstrip("$").replace(",", "."))
    if price <= 0:
        raise ValueError("bad price")
    return name, price


@router.message(Command("watch"))
async def cmd_watch(message: Message, command: CommandObject, client):
    if not client.ready():
        await message.answer("Каталог ще вантажиться, спробуй за хвилину.")
        return
    if not command.args:
        await message.answer("Формат: /watch <назва> <ціна>")
        return
    try:
        name, price = _parse_name_price(command.args)
    except ValueError:
        await message.answer(
            "Формат: /watch <назва> <ціна>\n"
            "напр.: /watch AWP | Asiimov (Field-Tested) 55"
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
    wid = await db.add_watch(message.from_user.id, message.chat.id, canonical, price)
    if wid is None:
        await message.answer("Таке стеження вже є (див. /list).")
        return

    extra = "" if exact else "\n(підібрав за схожістю)"
    await message.answer(
        f"Стежу [#{wid}]: {canonical}\n"
        f"Ціль: <= ${price:.2f}\n"
        f"Зараз: ${item.price:.2f} ({item.count} шт){extra}"
    )


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
async def cmd_list(message: Message):
    rows = await db.list_watches(message.from_user.id)
    if not rows:
        await message.answer("Порожньо. Додай через /watch.")
        return
    out = []
    for r in rows:
        if r["muted"]:
            state = " [muted]"
        elif r["triggered"]:
            state = " [спрацював]"
        else:
            state = ""
        last = f", зараз ${r['last_price']:.2f}" if r["last_price"] is not None else ""
        out.append(
            f"#{r['id']}  {r['skin_name']}  —  ціль <= ${r['target_price']:.2f}{last}{state}"
        )
    await message.answer("\n".join(out))


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
