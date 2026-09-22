"""Розбір подій WebSocket-каналу lis-skins `public:obtained-skins`.

Чиста функція без I/O — WS-клієнт (lis_ws.py) лише викликає її й застосовує
результат до LisCache. Формат події — з офіційної документації lis-skins:
{id, name, price, ..., event: "obtained_skin_added"|"obtained_skin_deleted"|"obtained_skin_price_changed"}
"""
from __future__ import annotations

_UPSERT_EVENTS = ("obtained_skin_added", "obtained_skin_price_changed")
_REMOVE_EVENTS = ("obtained_skin_deleted",)


def parse_market_event(data: dict):
    """-> ("upsert"|"remove", name, lot_id, price|None) або None, якщо подія незрозуміла."""
    event = data.get("event")
    if event not in _UPSERT_EVENTS and event not in _REMOVE_EVENTS:
        return None
    name = data.get("name")
    if not name:
        return None
    try:
        lot_id = int(data["id"])
    except (KeyError, TypeError, ValueError):
        return None

    if event in _REMOVE_EVENTS:
        return "remove", name, lot_id, None

    try:
        price = float(data["price"])
    except (KeyError, TypeError, ValueError):
        return None
    return "upsert", name, lot_id, price
