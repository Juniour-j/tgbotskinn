"""Тести форматування — позначка ⚡ для живої (WS) ціни lis-skins у виводі."""
from bot import handlers
from bot.sources import Quote


class _FakeMarket:
    def __init__(self, quotes, live=False):
        self._quotes = quotes  # [(key, label, Quote)]
        self._live = live

    def quotes(self, name):
        return self._quotes

    def lis_is_live(self, name):
        return self._live


def test_mkt_line_marks_live_lis_price():
    qs = [("lis", "lis-skins", Quote(0.11, 5, "u")),
          ("mcsgo", "market.csgo", Quote(0.13, 5, "u"))]
    m = _FakeMarket(qs, live=True)
    line = handlers._mkt_line("Kilowatt Case", m, short=True)
    assert "lis⚡" in line
    assert "$0.11" in line


def test_mkt_line_no_marker_when_not_live():
    qs = [("lis", "lis-skins", Quote(0.14, 5, "u"))]
    m = _FakeMarket(qs, live=False)
    line = handlers._mkt_line("Kilowatt Case", m, short=True)
    assert "⚡" not in line


def test_mkt_line_marker_only_on_lis_key():
    qs = [("lis", "lis-skins", Quote(0.14, 5, "u")),
          ("mcsgo", "market.csgo", Quote(0.10, 5, "u"))]
    m = _FakeMarket(qs, live=True)
    line = handlers._mkt_line("Kilowatt Case", m, short=False)
    assert "market.csgo⚡" not in line
    assert "lis-skins⚡" in line
