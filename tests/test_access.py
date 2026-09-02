import asyncio
import types

from bot.access import AccessMiddleware
from bot.config import _parse_ids


def test_parse_ids():
    assert _parse_ids("111, 222 333") == frozenset({111, 222, 333})
    assert _parse_ids("") == frozenset()
    assert _parse_ids("x, 5, ") == frozenset({5})


class FakeMsg:
    def __init__(self, uid, text="/list"):
        self.from_user = types.SimpleNamespace(id=uid)
        self.text = text
        self.answered = []

    async def answer(self, t):
        self.answered.append(t)


async def _handler(event, data):
    data.setdefault("ran", []).append(event.text)
    return "handled"


def test_allowed_user_passes():
    mw = AccessMiddleware(frozenset({111}))
    m = FakeMsg(111)
    data = {"event_from_user": m.from_user}
    assert asyncio.run(mw(_handler, m, data)) == "handled"
    assert data["ran"] == ["/list"]


def test_blocked_user_stopped_and_notified():
    mw = AccessMiddleware(frozenset({111}))
    m = FakeMsg(999)
    data = {"event_from_user": m.from_user}
    assert asyncio.run(mw(_handler, m, data)) is None
    assert "ran" not in data
    assert m.answered == ["Доступ обмежено."]


def test_empty_allowlist_is_open():
    mw = AccessMiddleware(frozenset())
    m = FakeMsg(42)
    data = {"event_from_user": m.from_user}
    assert asyncio.run(mw(_handler, m, data)) == "handled"
