"""Клавіатури Telegram — усе через кнопки, згруповано."""
from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

# нижня постійна клавіатура
MAIN_KB = ReplyKeyboardMarkup(
    keyboard=[
        [KeyboardButton(text="➕ Додати"), KeyboardButton(text="📋 Список")],
        [KeyboardButton(text="🔎 Знайти"), KeyboardButton(text="🔀 Порівняти")],
    ],
    resize_keyboard=True,
    is_persistent=True,
)

_HOME = InlineKeyboardButton(text="🏠 Меню", callback_data="menu")
_LIST = InlineKeyboardButton(text="📋 Список", callback_data="lst:0")

# популярні кейси для швидкого додавання
QUICK_ADD = (
    "Kilowatt Case",
    "Revolution Case",
    "Fever Case",
    "Gallery Case",
    "Dreams & Nightmares Case",
    "Recoil Case",
    "Fracture Case",
    "Snakebite Case",
)


def menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Мої стеження", callback_data="lst:0")],
        [InlineKeyboardButton(text="➕ Додати стеження", callback_data="add")],
        [InlineKeyboardButton(text="🔀 Порівняти ціни", callback_data="cmpask"),
         InlineKeyboardButton(text="🔎 Знайти скін", callback_data="find")],
        [InlineKeyboardButton(text="❓ Довідка", callback_data="help")],
    ])


def add_kb() -> InlineKeyboardMarkup:
    kb, row = [], []
    for i, n in enumerate(QUICK_ADD):
        row.append(InlineKeyboardButton(
            text="⚡ " + n.replace(" Case", ""), callback_data=f"qa:{i}"))
        if len(row) == 2:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    kb.append([_LIST, _HOME])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def list_kb(rows) -> InlineKeyboardMarkup:
    """Компактно: 2 кнопки на стеження (глибина + керувати)."""
    kb = []
    for r in rows[:20]:
        wid = r["id"]
        kb.append([
            InlineKeyboardButton(text=f"📊 Глибина #{wid}", callback_data=f"dep:{wid}"),
            InlineKeyboardButton(text=f"⚙️ Керувати #{wid}", callback_data=f"w:{wid}"),
        ])
    kb.append([
        InlineKeyboardButton(text="➕ Додати", callback_data="add"),
        InlineKeyboardButton(text="🔄 Оновити", callback_data="lst:0"),
    ])
    kb.append([_HOME])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def watch_kb(wid: int, muted: bool, open_links=None) -> InlineKeyboardMarkup:
    """Картка керування одним стеженням. open_links: [(label, url), ...]."""
    kb = []
    for label, url in (open_links or [])[:2]:
        kb.append([InlineKeyboardButton(text=f"🔗 Відкрити {label}", url=url)])
    kb.append([
        InlineKeyboardButton(text="📊 Глибина", callback_data=f"dep:{wid}"),
        InlineKeyboardButton(text="🔀 Порівняти", callback_data=f"cmp:{wid}"),
    ])
    mute = (("🔔 Увімкнути звук", f"unm:{wid}") if muted
            else ("🔕 Без звуку", f"mut:{wid}"))
    kb.append([
        InlineKeyboardButton(text="✏️ Змінити ціль", callback_data=f"ed:{wid}"),
        InlineKeyboardButton(text=mute[0], callback_data=mute[1]),
    ])
    kb.append([
        InlineKeyboardButton(text="🗑 Видалити", callback_data=f"del:{wid}"),
        _LIST,
    ])
    kb.append([_HOME])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def depth_kb(wid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Оновити", callback_data=f"dep:{wid}"),
         InlineKeyboardButton(text="⚙️ Керувати", callback_data=f"w:{wid}")],
        [_LIST, _HOME],
    ])


def after_add_kb(wid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Глибина", callback_data=f"dep:{wid}"),
         InlineKeyboardButton(text="⚙️ Керувати", callback_data=f"w:{wid}")],
        [_LIST, _HOME],
    ])


def find_kb(names) -> InlineKeyboardMarkup:
    kb = [[InlineKeyboardButton(text=n[:60], callback_data=f"pk:{i}")]
          for i, n in enumerate(names[:10])]
    kb.append([InlineKeyboardButton(text="➕ Додати вручну", callback_data="add"), _HOME])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_LIST, _HOME]])


def alert_kb(label: str, url: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text=f"🔗 Відкрити {label}", url=url),
    ]])
