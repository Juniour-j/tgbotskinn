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


def test_bulk_floor_skips_thin_bottom():
    d = _idx()
    # total 7419 -> thr = max(20, 74) = 74; перший рівень >= 74 це $0.44 (2287)
    assert d.bulk_floor("Case A") == 0.44
    assert d.bulk_floor("Nope") is None


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
