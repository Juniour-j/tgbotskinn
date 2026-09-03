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
        [KeyboardButton(text="🔎 Пошук"), KeyboardButton(text="❓ Довідка")],
    ],
    resize_keyboard=True,
)

_HOME = InlineKeyboardButton(text="🏠 меню", callback_data="menu")


def menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Мої стеження", callback_data="lst:0")],
        [InlineKeyboardButton(text="➕ Додати", callback_data="add"),
         InlineKeyboardButton(text="🔎 Знайти скін", callback_data="find")],
        [InlineKeyboardButton(text="❓ Як користуватись", callback_data="help")],
    ])


def list_kb(rows) -> InlineKeyboardMarkup:
    kb = []
    for r in rows[:12]:
        wid = r["id"]
        mute_btn = (
            InlineKeyboardButton(text=f"🔔 #{wid}", callback_data=f"unm:{wid}")
            if r["muted"]
            else InlineKeyboardButton(text=f"🔕 #{wid}", callback_data=f"mut:{wid}")
        )
        kb.append([
            InlineKeyboardButton(text=f"📊 #{wid}", callback_data=f"dep:{wid}"),
            InlineKeyboardButton(text=f"🔀 #{wid}", callback_data=f"cmp:{wid}"),
            mute_btn,
            InlineKeyboardButton(text=f"🗑 #{wid}", callback_data=f"del:{wid}"),
        ])
    kb.append([
        InlineKeyboardButton(text="➕ Додати", callback_data="add"),
        InlineKeyboardButton(text="🔄 Оновити", callback_data="lst:0"),
    ])
    kb.append([_HOME])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def depth_kb(wid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Оновити", callback_data=f"dep:{wid}"),
         InlineKeyboardButton(text="🔀 Порівняти", callback_data=f"cmp:{wid}")],
        [InlineKeyboardButton(text="📋 Список", callback_data="lst:0"), _HOME],
    ])


def after_add_kb(wid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"📊 глибина #{wid}", callback_data=f"dep:{wid}"),
         InlineKeyboardButton(text=f"🔀 порівняти #{wid}", callback_data=f"cmp:{wid}")],
        [InlineKeyboardButton(text=f"🗑 прибрати #{wid}", callback_data=f"del:{wid}"),
         InlineKeyboardButton(text="📋 Список", callback_data="lst:0")],
        [_HOME],
    ])


def find_kb(names) -> InlineKeyboardMarkup:
    kb = [[InlineKeyboardButton(text=n[:60], callback_data=f"pk:{i}")]
          for i, n in enumerate(names[:10])]
    kb.append([InlineKeyboardButton(text="➕ Додати вручну", callback_data="add"), _HOME])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="📋 Список", callback_data="lst:0"), _HOME,
    ]])
