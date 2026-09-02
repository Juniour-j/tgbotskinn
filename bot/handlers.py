"""Команди Telegram-бота."""
from __future__ import annotations

import asyncio
import logging
import re

from aiogram import Router
from aiogram.filters import Command, CommandObject
from aiogram.types import Message

from . import db, matcher

log = logging.getLogger("handlers")
router = Router()

HELP = (
    "Стежу за цінами скінів на lis-skins.com (CS2).\n\n"
    "/watch <назва> <ціна> — стежити за ціною\n"
    "    напр.: /watch AWP | Asiimov (Field-Tested) 55\n"
    "/watch <назва> <ціна> x<шт> — стежити за ОБСЯГОМ:\n"
    "    спрацює, коли буде >= <шт> лотів по ціні <= <ціна>\n"
    "    напр.: /watch Sealed Dead Hand Terminal 0.44 x200\n"
    "/depth <id> — драбина цін (скільки лотів по якій ціні)\n"
    "/find <текст> — знайти точну назву скіна\n"
    "/list — мої стеження\n"
    "/unwatch <id> — прибрати\n"
    "/mute <id> | /unmute <id> — сповіщення\n"
    "/whoami — мій Telegram id\n\n"
    "Ціни в доларах. Ціна перевіряється ~щохвилини, глибина — раз на ~15 хв.\n"
    "Сповіщення приходить один раз; знову спрацює, якщо умова знову перестане й почне виконуватись."
)

_QTY_RE = re.compile(r"^[xхXХ*](\d+)$")


@router.message(Command("start", "help"))
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
    lines = [
        f"{verb} [#{wid}]: {canonical}",
        f"Ціль: <= ${price:.2f}",
    ]

    d_floor = depth.floor(canonical)
    d_count = depth.count(canonical)
    if qty > 1:
        have = depth.qty_at_or_below(canonical, price)
        if have is None:
            lines.append(f"Треба: >= {qty} шт (глибина зʼявиться за хвилину)")
        else:
            lines.append(f"Треба: >= {qty} шт (зараз по <= ${price:.2f}: {have} шт)")

    if d_floor is not None:
        lines.append(f"Мін. ціна зараз: ${d_floor:.2f} ({d_count} шт усього)")
    elif item is not None:
        lines.append(f"Мін. ціна зараз: ${item.price:.2f} (орієнтовно, уточниться за хвилину)")

    if depth.floor(canonical) is None:
        asyncio.create_task(_kick_depth(depth))
    if not exact:
        lines.append("(підібрав за схожістю)")
    await message.answer("\n".join(lines))


async def _kick_depth(depth):
    try:
        names = await db.watched_names()
        if names:
            await depth.refresh(names)
    except Exception:
        log.exception("ad-hoc depth refresh failed")


@router.message(Command("depth"))
async def cmd_depth(message: Message, command: CommandObject, client, depth):
    try:
        wid = int((command.args or "").strip())
    except ValueError:
        await message.answer("Формат: /depth <id> (id з /list)")
        return
    w = await db.get_watch(message.from_user.id, wid)
    if w is None:
        await message.answer(f"Немає стеження #{wid}.")
        return
    name = w["skin_name"]
    if not depth.has(name):
        await message.answer(
            f"Глибина для «{name}» ще не завантажена.\n"
            "Оновлюється раз на ~15 хв і лише для стежень з x<шт>. Спробуй пізніше."
        )
        asyncio.create_task(_kick_depth(depth))
        return
    rungs = depth.ladder(name, 12)
    cum = 0
    out = [name, f"глибина оновлена {depth.age_min()} хв тому", "", "ціна    шт     сумарно"]
    for p, q in rungs:
        cum += q
        out.append(f"${p:<6.2f} {q:<6} {cum}")
    have = depth.qty_at_or_below(name, w["target_price"])
    out.append("")
    out.append(f"по <= ${w['target_price']:.2f}: {have} шт (ціль x{w['min_qty']})")
    await message.answer("\n".join(out))


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
        name = r["skin_name"]
        item = client.lookup(name)
        d_floor = depth.floor(name)
        d_count = depth.count(name)
        # актуальна ціна: з повного експорту, інакше з csgo.json, інакше last_price
        if d_floor is not None:
            now = f"${d_floor:.2f} ({d_count} шт)"
        elif item is not None:
            now = f"${item.price:.2f} (~)"
        elif r["last_price"] is not None:
            now = f"${r['last_price']:.2f} (~)"
        else:
            now = "?"

        if r["min_qty"] > 1:
            have = depth.qty_at_or_below(name, r["target_price"])
            have_s = f"{have} шт" if have is not None else "?"
            tail = (f"обсяг: {have_s} по <= ${r['target_price']:.2f} "
                    f"(треба x{r['min_qty']}), зараз від {now}")
        else:
            tail = f"зараз {now}, ціль <= ${r['target_price']:.2f}"
        out.append(f"#{r['id']}  {name}  —  {tail}{state}")
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
