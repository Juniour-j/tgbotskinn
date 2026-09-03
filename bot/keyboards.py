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


PAGE = 8  # стежень на сторінку списку


def menu_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Мої стеження", callback_data="lst:0")],
        [InlineKeyboardButton(text="➕ Додати стеження", callback_data="add")],
        [InlineKeyboardButton(text="🔀 Порівняти ціни", callback_data="cmpask"),
         InlineKeyboardButton(text="💸 Топ", callback_data="top:cheap:0")],
        [InlineKeyboardButton(text="🔎 Знайти скін", callback_data="find"),
         InlineKeyboardButton(text="📈 Статус", callback_data="status")],
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


_SORTS = ("state", "price", "name")
_SORT_LBL = {"state": "за станом", "price": "за ціною", "name": "за назвою"}


def list_kb(page_rows, page: int, pages: int, sort: str,
            has_triggered: bool, undo: bool = False) -> InlineKeyboardMarkup:
    kb = []
    for r in page_rows:
        wid = r["id"]
        kb.append([
            InlineKeyboardButton(text=f"📊 #{wid}", callback_data=f"dep:{wid}"),
            InlineKeyboardButton(text=f"⚙️ Керувати #{wid}", callback_data=f"w:{wid}"),
        ])
    if undo:
        kb.append([InlineKeyboardButton(text="↩️ Повернути видалене",
                                        callback_data="undo")])
    if pages > 1:
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(text="◀", callback_data=f"lst:{page-1}"))
        nav.append(InlineKeyboardButton(text=f"{page+1}/{pages}", callback_data=f"lst:{page}"))
        if page < pages - 1:
            nav.append(InlineKeyboardButton(text="▶", callback_data=f"lst:{page+1}"))
        kb.append(nav)
    nxt = _SORTS[(_SORTS.index(sort) + 1) % len(_SORTS)]
    kb.append([
        InlineKeyboardButton(text=f"⇅ {_SORT_LBL[sort]}", callback_data=f"srt:{nxt}"),
        InlineKeyboardButton(text="🔄 Оновити", callback_data=f"lst:{page}"),
    ])
    bulk = [InlineKeyboardButton(text="🔕 стишити всі", callback_data="allmut")]
    if has_triggered:
        bulk.append(InlineKeyboardButton(text="🧹 прибрати спрацьовані",
                                         callback_data="clrdone"))
    kb.append(bulk)
    kb.append([InlineKeyboardButton(text="➕ Додати", callback_data="add"), _HOME])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def snooze_kb(wid: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔕 1 год", callback_data=f"snz:{wid}:60"),
         InlineKeyboardButton(text="🔕 8 год", callback_data=f"snz:{wid}:480"),
         InlineKeyboardButton(text="🔕 24 год", callback_data=f"snz:{wid}:1440")],
        [InlineKeyboardButton(text="🔕 назавжди", callback_data=f"mut:{wid}"),
         InlineKeyboardButton(text="🔔 увімкнути", callback_data=f"unm:{wid}")],
        [InlineKeyboardButton(text="⬅️ до картки", callback_data=f"w:{wid}"), _HOME],
    ])


def top_kb(mode: str, names=None) -> InlineKeyboardMarkup:
    kb, row = [], []
    for i, n in enumerate((names or [])[:6]):
        row.append(InlineKeyboardButton(
            text="⚡ " + n.replace(" Case", "").replace(" Capsule", "")[:18],
            callback_data=f"tp:{i}"))
        if len(row) == 2:
            kb.append(row)
            row = []
    if row:
        kb.append(row)
    other = "spread" if mode == "cheap" else "cheap"
    lbl = "↔️ розкид ринків" if other == "spread" else "💸 найдешевші"
    kb.append([InlineKeyboardButton(text=lbl, callback_data=f"top:{other}:0"),
               InlineKeyboardButton(text="🔄", callback_data=f"top:{mode}:0")])
    kb.append([_LIST, _HOME])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def target_kb(prices, edit_wid: int | None = None):
    """3 підказані цілі + рядок навігації. edit_wid → edp:, інакше pp:."""
    pfx = f"edp:{edit_wid}:" if edit_wid is not None else "pp:"
    kb = [[InlineKeyboardButton(text=f"🎯 ${p:.2f}", callback_data=f"{pfx}{p:.2f}")
           for p in prices]]
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
    mute = ("🔔 Звук", f"unm:{wid}") if muted else ("🔕 Тиша…", f"snz:{wid}")
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


def find_kb(items) -> InlineKeyboardMarkup:
    """items: список назв або (назва, ціна|None)."""
    kb = []
    for i, it in enumerate(items[:10]):
        if isinstance(it, tuple):
            n, p = it
            txt = f"{n[:44]}  ${p:.2f}" if p else n[:60]
        else:
            txt = it[:60]
        kb.append([InlineKeyboardButton(text=txt, callback_data=f"pk:{i}")])
    kb.append([InlineKeyboardButton(text="➕ Додати вручну", callback_data="add"), _HOME])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[_LIST, _HOME]])


def alert_kb(label: str, url: str, wid: int) -> InlineKeyboardMarkup:
    rows = []
    if url:
        rows.append([InlineKeyboardButton(text=f"🔗 Відкрити {label}", url=url)])
    rows.append([
        InlineKeyboardButton(text="🔕 1 год", callback_data=f"snz:{wid}:60"),
        InlineKeyboardButton(text="🔕 8 год", callback_data=f"snz:{wid}:480"),
        InlineKeyboardButton(text="✅ ок", callback_data=f"ok:{wid}"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)
