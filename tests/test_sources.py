import types

from bot.market import Market
from bot.sources import McsgoSource, SkinportSource, Quote


def _mk(cls):
    return cls("http://x", 30.0)


def test_mcsgo_parse():
    s = _mk(McsgoSource)
    payload = {"success": True, "items": [
        {"market_hash_name": "Kilowatt Case", "price": "0.128", "volume": "340"},
        {"market_hash_name": "Bad", "price": "0"},
        {"market_hash_name": "NoPrice"},
    ]}
    s._by_norm = s._parse(payload)
    q = s.lookup("Kilowatt Case")
    assert q is not None and abs(q.price - 0.128) < 1e-9 and q.qty == 340
    assert "market.csgo.com" in q.url
    assert s.lookup("Bad") is None and s.lookup("NoPrice") is None
    # нормалізація: інший регістр / зайві пробіли
    assert s.lookup("kilowatt   case") is not None


def test_skinport_parse():
    s = _mk(SkinportSource)
    payload = [
        {"market_hash_name": "Fever Case", "min_price": 0.54, "quantity": 190,
         "item_page": "https://skinport.com/item/fever-case"},
        {"market_hash_name": "Empty", "min_price": None, "quantity": 0},
    ]
    s._by_norm = s._parse(payload)
    q = s.lookup("Fever Case")
    assert q is not None and q.price == 0.54 and q.qty == 190
    assert s.lookup("Empty") is None


class _Depth:
    def __init__(self, prices):
        self._p = prices          # name -> site_price
    def site_price(self, n): return self._p.get(n)
    def count(self, n): return 3 if n in self._p else None


class _Client:
    _known = {"Kilowatt Case"}
    def lookup(self, n):
        if n in self._known:
            return types.SimpleNamespace(price=9.99, count=1, url="lisurl")
        return None


class _Src:
    def __init__(self, key, label, data):
        self.key, self.label, self._d = key, label, data
    def lookup(self, name): return self._d.get(name)


def _market():
    depth = _Depth({"Kilowatt Case": 0.14})
    mc = _Src("mcsgo", "market.csgo", {"Kilowatt Case": Quote(0.128, 340, "u")})
    sp = _Src("skinport", "skinport", {"Kilowatt Case": Quote(0.15, 190, "u")})
    return Market(_Client(), depth, [mc, sp])


def test_market_quotes_and_best():
    m = _market()
    qs = m.quotes("Kilowatt Case")
    assert [k for k, _, _ in qs] == ["lis", "mcsgo", "skinport"]
    key, label, q = m.best("Kilowatt Case")
    assert key == "mcsgo" and q.price == 0.128
    assert m.best("Unknown") is None


def test_market_summary():
    m = _market()
    assert m.summary("Kilowatt Case") == "lis-skins $0.14 · market.csgo $0.13 · skinport $0.15"
    assert m.summary("Unknown") == ""
