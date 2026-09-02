"""Клавіатури Telegram."""
from __future__ import annotations

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

# нижня постійна клавіатура
MAIN_KB = ReplyKeyboardMarkup(
    keyboard=[[
        KeyboardButton(text="📋 Список"),
        KeyboardButton(text="❓ Довідка"),
    ]],
    resize_keyboard=True,
)


def list_kb(rows) -> InlineKeyboardMarkup | None:
    """Під кожним стеженням: глибина / мут / видалити."""
    kb = []
    for r in rows[:12]:
        wid = r["id"]
        mute_btn = (
            InlineKeyboardButton(text=f"🔔 #{wid}", callback_data=f"unm:{wid}")
            if r["muted"]
            else InlineKeyboardButton(text=f"🔕 #{wid}", callback_data=f"mut:{wid}")
        )
        kb.append([
            InlineKeyboardButton(text=f"📊 глибина #{wid}", callback_data=f"dep:{wid}"),
            mute_btn,
            InlineKeyboardButton(text=f"🗑 #{wid}", callback_data=f"del:{wid}"),
        ])
    kb.append([InlineKeyboardButton(text="🔄 оновити", callback_data="lst:0")])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def depth_kb(wid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🔄 оновити", callback_data=f"dep:{wid}"),
        InlineKeyboardButton(text="📋 список", callback_data="lst:0"),
    ]])
