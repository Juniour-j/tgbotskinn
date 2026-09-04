import asyncio
import types

import pytest

from bot import db, handlers
from bot.handlers import (
    _money_signed,
    _parse_buy_args,
    _parse_sold_args,
)


# ---------- парсери ----------

def test_parse_buy_args():
    assert _parse_buy_args("Kilowatt Case 200 0.11") == ("Kilowatt Case", 200, 0.11)
    assert _parse_buy_args("AWP | Asiimov (FT) 3 55") == ("AWP | Asiimov (FT)", 3, 55.0)
    assert _parse_buy_args("Fever Case 200 $0,13") == ("Fever Case", 200, 0.13)


def test_parse_buy_args_bad():
    for bad in ("", "OnlyName 5", "Name 0 0.1", "Name 5 0", "Name 5 -1"):
        with pytest.raises(ValueError):
            _parse_buy_args(bad)


def test_parse_sold_args():
    assert _parse_sold_args("") == (None, None)
    assert _parse_sold_args("50") == (50, None)
    assert _parse_sold_args("50 0.13") == (50, 0.13)
    assert _parse_sold_args("0.13") == (None, 0.13)          # лише ціна -> усе
    assert _parse_sold_args("all 0.13") == (None, 0.13)
    assert _parse_sold_args("all") == (None, None)
    assert _parse_sold_args("усе 0.2") == (None, 0.2)


def test_parse_sold_args_bad():
    for bad in ("50 0", "0 0.1", "50 -0.1"):
        with pytest.raises(ValueError):
            _parse_sold_args(bad)


def test_money_signed():
    assert _money_signed(3.6) == "+$3.60"
    assert _money_signed(-3.6) == "−$3.60"
    assert _money_signed(0) == "+$0.00"


# ---------- фейковий ринок ----------

class _Q:
    def __init__(self, p):
        self.price = p
        self.buy_order = 0.0
        self.url = "http://x"
        self.qty = 5


class _Market:
    def __init__(self, prices):
        self._p = prices

    def best(self, name):
        p = self._p.get(name)
        return ("lis", "lis-skins", _Q(p)) if p is not None else None


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro) if False else asyncio.run(coro)


# ---------- сценарії ----------

def test_portfolio_view_empty(tmp_path):
    async def go():
        await db.init_db(str(tmp_path / "pf.db"))
        try:
            txt, kb = await handlers._portfolio_view(1, _Market({}))
            assert "порожній" in txt
        finally:
            await db.close()
    asyncio.run(go())


def test_buy_then_portfolio_pnl(tmp_path):
    async def go():
        await db.init_db(str(tmp_path / "pf2.db"))
        try:
            client = types.SimpleNamespace(names={"Kilowatt Case"})
            mkt = _Market({"Kilowatt Case": 0.13})
            txt, _ = await handlers._do_buy(1, "Kilowatt Case", 200, 0.10, client, mkt)
            assert "Записав купівлю</b> #1" in txt
            assert "$20.00" in txt and "$26.00" in txt   # вклав / зараз
            # 200*0.10=20 вклав, 200*0.13=26 зараз -> +$6.00 (+30%)
            assert "+$6.00" in txt and "+30%" in txt
            assert "Разом" in txt

            rows = await db.list_holdings(1)
            assert len(rows) == 1 and rows[0]["qty"] == 200
        finally:
            await db.close()
    asyncio.run(go())


def test_partial_sell_realized_pnl(tmp_path):
    async def go():
        await db.init_db(str(tmp_path / "pf3.db"))
        try:
            mkt = _Market({"Fever Case": 0.20})
            hid = await db.add_holding(1, "Fever Case", 100, 0.10)
            txt, _ = await handlers._do_sell(1, hid, 40, 0.15, mkt)
            # (0.15-0.10)*40 = +$2.00 realized
            assert "Продано</b> 40 шт" in txt and "+$2.00" in txt
            left = await db.get_holding(1, hid)
            assert left["qty"] == 60

            # закрити решту за ринком (ціну не задаємо)
            txt2, _ = await handlers._do_sell(1, hid, None, None, mkt)
            assert "Продано</b> 60 шт" in txt2
            assert await db.get_holding(1, hid) is None
        finally:
            await db.close()
    asyncio.run(go())


def test_sell_missing_holding(tmp_path):
    async def go():
        await db.init_db(str(tmp_path / "pf4.db"))
        try:
            txt, _ = await handlers._do_sell(1, 999, None, None, _Market({}))
            assert "Немає позиції #999" in txt
        finally:
            await db.close()
    asyncio.run(go())
