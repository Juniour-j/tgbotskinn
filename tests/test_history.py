import asyncio
import time

from bot import db, history


# ---------- чисті функції аналізу ----------

def test_sparkline_basic():
    s = history.sparkline([1, 2, 3, 4, 5])
    assert len(s) == 5
    assert s[0] == "▁" and s[-1] == "█"


def test_sparkline_edge_cases():
    assert history.sparkline([]) == ""
    assert history.sparkline([5]) == ""
    flat = history.sparkline([3, 3, 3, 3])
    assert set(flat) == {"▄"} and len(flat) == 4


def test_sparkline_downsamples_to_width():
    assert len(history.sparkline(list(range(200)), width=24)) == 24


def test_stats():
    st = history.stats([(1, 10.0), (2, 20.0), (3, 30.0)])
    assert st == {"lo": 10.0, "hi": 30.0, "avg": 20.0,
                  "first": 10.0, "last": 30.0, "n": 3}
    assert history.stats([]) is None


def test_change_pct():
    assert history.change_pct([(1, 100.0), (2, 88.0)]) == -12.0
    assert history.change_pct([(1, 100.0), (2, 110.0)]) == 10.0
    assert history.change_pct([(1, 5.0)]) is None
    assert history.change_pct([(1, 0.0), (2, 3.0)]) is None


def test_cheaper_than_pct():
    series = [(i, p) for i, p in enumerate([10, 11, 12, 9, 13])]
    # поточна 9.5 -> вища була у 4 з 5 випадків -> 80%
    assert history.cheaper_than_pct(series, 9.5) == 80.0
    # мало даних
    assert history.cheaper_than_pct([(1, 10.0)], 9.0) is None


# ---------- сховище історії ----------

def _fresh_db(path):
    async def go():
        await db.init_db(str(path))
        try:
            hour = int(time.time() // 3600)
            await db.record_prices([("Kilowatt Case", 0.10), ("Fever Case", 0.50)])
            # дозаписати попередню годину вручну
            await db._db.execute(
                "INSERT OR REPLACE INTO price_hist(name, hour, price) VALUES (?,?,?)",
                ("Kilowatt Case", hour - 5, 0.14))
            await db._db.commit()

            s = await db.price_series("Kilowatt Case", 24)
            assert [p for _, p in s] == [0.14, 0.10]

            bulk = await db.price_series_bulk(["Kilowatt Case", "Fever Case", "X"], 24)
            assert set(bulk) == {"Kilowatt Case", "Fever Case"}
            assert bulk["Fever Case"] == [(hour, 0.50)]

            # upsert у межах години — не дублює
            await db.record_prices([("Kilowatt Case", 0.09)])
            s2 = await db.price_series("Kilowatt Case", 24)
            assert [p for _, p in s2] == [0.14, 0.09]

            n = await db.prune_prices(keep_days=0)
            assert n >= 1
        finally:
            await db.close()

    asyncio.run(go())


def test_price_hist_roundtrip(tmp_path):
    _fresh_db(tmp_path / "h.db")


def test_none_prices_skipped(tmp_path):
    async def go():
        await db.init_db(str(tmp_path / "n.db"))
        try:
            await db.record_prices([("A", None), ("B", 1.0)])
            assert await db.price_series("A", 24) == []
            assert len(await db.price_series("B", 24)) == 1
        finally:
            await db.close()

    asyncio.run(go())


# ---------- портфель ----------

def test_holdings_roundtrip(tmp_path):
    async def go():
        await db.init_db(str(tmp_path / "p.db"))
        try:
            hid = await db.add_holding(1, "Kilowatt Case", 200, 0.11)
            rows = await db.list_holdings(1)
            assert len(rows) == 1 and rows[0]["qty"] == 200

            assert await db.reduce_holding(1, hid, 50) is True
            assert (await db.get_holding(1, hid))["qty"] == 150

            assert await db.reduce_holding(1, hid, 999) is True
            assert await db.get_holding(1, hid) is None
            assert await db.list_holdings(1) == []

            assert await db.remove_holding(1, 123) is False
        finally:
            await db.close()

    asyncio.run(go())
