import types

import pytest

from bot.depth import DepthIndex
from bot.handlers import _parse_watch_args


def _idx() -> DepthIndex:
    cfg = types.SimpleNamespace(full_export_url="http://x", http_timeout=30.0)
    d = DepthIndex(cfg)
    # Sealed Dead Hand Terminal-подібна драбина: дно тонке, маса вище
    d._ladders = {
        "Case A": {0.28: 2, 0.32: 1, 0.42: 36, 0.44: 2287, 0.48: 5093},
    }
    return d


def test_qty_at_or_below():
    d = _idx()
    assert d.qty_at_or_below("Case A", 0.28) == 2
    assert d.qty_at_or_below("Case A", 0.42) == 39
    assert d.qty_at_or_below("Case A", 0.44) == 2326
    assert d.qty_at_or_below("Case A", 1.00) == 7419


def test_buyable_qty_excludes_dust_below_site_price():
    cfg = types.SimpleNamespace(full_export_url="http://x", http_timeout=30.0)
    d = DepthIndex(cfg)
    # site_price тут = 0.40 (0.28×6 — сміття перед розривом)
    d._ladders = {"C": {0.28: 6, 0.40: 12, 0.41: 180, 0.44: 2000}}
    assert d.site_price("C") == 0.40
    assert d.buyable_qty("C", 0.38) == 0        # як «Filters match 0» на сайті
    assert d.buyable_qty("C", 0.41) == 12 + 180
    assert d.buyable_qty("C", 1.0) == 12 + 180 + 2000
    assert d.buyable_qty("Nope", 1.0) is None


def test_unknown_name_returns_none():
    d = _idx()
    assert d.qty_at_or_below("Nope", 1.0) is None
    assert d.has("Nope") is False


def test_floor_count_and_ladder():
    d = _idx()
    assert d.floor("Case A") == 0.28
    assert d.count("Case A") == 2 + 1 + 36 + 2287 + 5093
    assert d.count("Nope") is None
    assert d.ladder("Case A", 3) == [(0.28, 2), (0.32, 1), (0.42, 36)]


def test_site_price_skips_fresh_bottom_before_gap():
    cfg = types.SimpleNamespace(full_export_url="http://x", http_timeout=30.0)
    d = DepthIndex(cfg)
    # 11 свіжих лотів на $0.28, потім розрив до реального ринку $0.37+
    d._ladders = {"X": {0.28: 11, 0.37: 2, 0.40: 220, 0.41: 180, 0.44: 2311}}
    assert d.site_price("X") == 0.37

    # чистий ринок — флор одразу вагомий
    d._ladders = {"Y": {0.44: 2311, 0.48: 5000}}
    assert d.site_price("Y") == 0.44

    # тонкий флор, але без розриву — лишаємо
    d._ladders = {"Z": {0.54: 5, 0.56: 40, 0.57: 1790}}
    assert d.site_price("Z") == 0.54

    assert d.site_price("Nope") is None


def test_fill_price():
    d = _idx()
    # ladder: 0.28:2, 0.32:1, 0.42:36, 0.44:2287, 0.48:5093
    assert d.fill_price("Case A", 1) == 0.28
    assert d.fill_price("Case A", 3) == 0.32
    assert d.fill_price("Case A", 40) == 0.44      # 2+1+36=39 < 40 -> наступний рівень
    assert d.fill_price("Case A", 39) == 0.42
    assert d.fill_price("Case A", 100) == 0.44
    assert d.fill_price("Case A", 10_000) is None  # усього ~7419
    assert d.fill_price("Nope", 1) is None


@pytest.mark.parametrize("raw,expected", [
    ("AWP | Asiimov (Field-Tested) 55", ("AWP | Asiimov (Field-Tested)", 55.0, 1)),
    ("Sealed Dead Hand Terminal 0.44 x200", ("Sealed Dead Hand Terminal", 0.44, 200)),
    ("Kilowatt Case 0,13 х50", ("Kilowatt Case", 0.13, 50)),
    ("Fever Case $0.54 X10", ("Fever Case", 0.54, 10)),
])
def test_parse_watch_args_ok(raw, expected):
    assert _parse_watch_args(raw) == expected


@pytest.mark.parametrize("raw", ["", "OnlyName", "Name x50", "Name -1", "Name 0"])
def test_parse_watch_args_bad(raw):
    with pytest.raises(ValueError):
        _parse_watch_args(raw)
