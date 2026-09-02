"""Обмеження доступу до бота за Telegram user id."""
from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject

log = logging.getLogger("access")


class AccessMiddleware(BaseMiddleware):
    """Пропускає лише користувачів зі списку. Порожній список = дозволено всім."""

    def __init__(self, allowed: frozenset[int]):
        self.allowed = allowed

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        if not self.allowed:
            return await handler(event, data)

        user = data.get("event_from_user")
        if user is not None and user.id in self.allowed:
            return await handler(event, data)

        log.info("blocked user id=%s", getattr(user, "id", "?"))
        reply = getattr(event, "answer", None)
        if callable(reply):
            try:
                await reply("Доступ обмежено.")
            except Exception:
                pass
        return None
