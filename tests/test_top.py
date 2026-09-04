import asyncio
import time
import types

from bot import db, handlers
from bot.market import Market
from bot.sources import Quote


class _ItemsSrc:
    def __init__(self, key, label, items):
        self.key, self.label, self._items = key, label, list(items)

    def items(self):
        return list(self._items)

    def lookup(self, name):
        for _, q in self._items:
            if q.name == name:
                return q
        return None


def _mkt(items):
    return Market(types.SimpleNamespace(lookup=lambda n: None), None,
                  [_ItemsSrc("mc", "market.csgo", items)])


def test_case_names_strict_cases_only():
    m = _mkt([
        ("kilowatt case", Quote(0.11, 5, "u", 0.0, "Kilowatt Case")),
        ("fever case", Quote(0.30, 5, "u", 0.0, "Fever Case")),
        ("some capsule", Quote(0.05, 5, "u", 0.0, "Some Sticker Capsule")),
        ("cool pin", Quote(2.0, 5, "u", 0.0, "Cool Pin")),
        ("kit box", Quote(0.40, 5, "u", 0.0, "Radicals Music Kit Box")),
        ("dust", Quote(0.01, 5, "u", 0.0, "Cheap Case")),   # < 0.03 -> відкидається
    ])
    assert m.case_names() == ["Kilowatt Case", "Fever Case"]


def test_top_cheapest_excludes_non_cases():
    m = _mkt([
        ("a", Quote(0.11, 5, "u", 0.0, "Kilowatt Case")),
        ("b", Quote(0.02, 5, "u", 0.0, "AK-47 | Redline")),      # не кейс
        ("c", Quote(0.07, 5, "u", 0.0, "Glove Capsule")),        # не кейс (строго)
    ])
    rows = m.top_cheapest(10)
    assert [n for n, _, _ in rows] == ["Kilowatt Case"]


def test_top_movers_splits_drops_and_rises(tmp_path):
    async def go():
        await db.init_db(str(tmp_path / "mv.db"))
        try:
            m = _mkt([
                ("a", Quote(0.10, 5, "u", 0.0, "A Case")),
                ("b", Quote(0.20, 5, "u", 0.0, "B Case")),
                ("c", Quote(0.50, 5, "u", 0.0, "C Case")),   # без історії -> ігнор
            ])
            hour = int(time.time() // 3600)
            for i, p in enumerate([0.14, 0.135, 0.13, 0.125, 0.12, 0.115, 0.11, 0.10]):
                await db._db.execute(
                    "INSERT OR REPLACE INTO price_hist VALUES (?,?,?)",
                    ("A Case", hour - 30 + i * 3, p))
            for i, p in enumerate([0.18, 0.185, 0.19, 0.195, 0.20, 0.20, 0.20, 0.20]):
                await db._db.execute(
                    "INSERT OR REPLACE INTO price_hist VALUES (?,?,?)",
                    ("B Case", hour - 30 + i * 3, p))
            await db._db.commit()

            drops, rises = await handlers._top_movers(m)
            assert [n for n, _, _ in drops] == ["A Case"] and drops[0][1] < 0
            assert [n for n, _, _ in rises] == ["B Case"] and rises[0][1] > 0
        finally:
            await db.close()

    asyncio.run(go())


def test_top_view_move_mode_no_data(tmp_path):
    async def go():
        await db.init_db(str(tmp_path / "mv2.db"))
        try:
            m = _mkt([("a", Quote(0.10, 5, "u", 0.0, "A Case"))])
            txt, kb = await handlers._top_view(1, m, "move")
            assert "рух за 7" in txt.lower()
        finally:
            await db.close()

    asyncio.run(go())
