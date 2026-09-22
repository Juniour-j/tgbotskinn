import types

from bot.lis_cache import LisCache
from bot.market import Market
from bot.sources import McsgoSource, SkinportSource, Quote


def _mk(cls):
    return cls("http://x", 30.0)


def test_mcsgo_parse():
    s = _mk(McsgoSource)
    # class_instance-фід: items — словник classid_instanceid -> {...}
    payload = {"success": True, "items": {
        "1_1": {"market_hash_name": "Kilowatt Case", "price": "0.315", "buy_order": 0.10},
        "1_2": {"market_hash_name": "Kilowatt Case", "price": "0.128", "buy_order": 0.098},
        "2_1": {"market_hash_name": "Bad", "price": "0"},
        "3_1": {"market_hash_name": "NoPrice"},
    }}
    s._by_norm = s._parse(payload)
    q = s.lookup("Kilowatt Case")
    assert q is not None and abs(q.price - 0.128) < 1e-9   # беремо найдешевший
    assert abs(q.buy_order - 0.098) < 1e-9
    assert q.name == "Kilowatt Case"
    assert "market.csgo.com" in q.url
    assert s.lookup("Bad") is None and s.lookup("NoPrice") is None
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


# ---------- живий кеш lis-skins (WS) ----------

def _market_with_cache(cache):
    depth = _Depth({"Kilowatt Case": 0.14})
    mc = _Src("mcsgo", "market.csgo", {"Kilowatt Case": Quote(0.128, 340, "u")})
    return Market(_Client(), depth, [mc], lis_cache=cache)


def test_lis_quote_prefers_live_cache_over_depth():
    cache = LisCache()
    cache.upsert("Kilowatt Case", 1, 0.09)
    cache.upsert("Kilowatt Case", 2, 0.10)
    m = _market_with_cache(cache)
    qs = dict((k, q) for k, _, q in m.quotes("Kilowatt Case"))
    assert abs(qs["lis"].price - 0.09) < 1e-9   # не 0.14 з депсу
    assert qs["lis"].qty == 2                   # скільки лотів у кеші зараз
    assert m.lis_is_live("Kilowatt Case") is True


def test_lis_quote_falls_back_to_depth_when_cache_has_no_data():
    cache = LisCache()  # порожній для цієї назви
    m = _market_with_cache(cache)
    qs = dict((k, q) for k, _, q in m.quotes("Kilowatt Case"))
    assert abs(qs["lis"].price - 0.14) < 1e-9
    assert m.lis_is_live("Kilowatt Case") is False


def test_market_without_lis_cache_arg_behaves_as_before():
    m = _market()  # без lis_cache взагалі
    assert m.lis_is_live("Kilowatt Case") is False
    qs = dict((k, q) for k, _, q in m.quotes("Kilowatt Case"))
    assert abs(qs["lis"].price - 0.14) < 1e-9


def test_lis_buyable_qty_prefers_live_cache():
    cache = LisCache()
    cache.upsert("Kilowatt Case", 1, 0.19)
    cache.upsert("Kilowatt Case", 2, 0.19)
    cache.upsert("Kilowatt Case", 3, 0.30)
    m = _market_with_cache(cache)
    assert m.lis_buyable_qty("Kilowatt Case", 0.19) == 2


def test_lis_buyable_qty_falls_back_to_depth_when_not_live():
    depth = _Depth({"Kilowatt Case": 0.14})
    depth.buyable_qty = lambda name, price: 77  # фейкова депс-відповідь
    m = Market(_Client(), depth, [], lis_cache=LisCache())  # порожній кеш для назви
    assert m.lis_buyable_qty("Kilowatt Case", 0.14) == 77


def test_lis_status_reports_active_state_and_name_count():
    m_off = _market()
    assert m_off.lis_status() == {"active": False, "names": 0}

    cache = LisCache()
    cache.upsert("Kilowatt Case", 1, 0.09)
    cache.upsert("Fever Case", 2, 0.30)
    m_on = _market_with_cache(cache)
    assert m_on.lis_status() == {"active": True, "names": 2}
