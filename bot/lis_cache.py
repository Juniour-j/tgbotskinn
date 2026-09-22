"""Живий кеш лотів lis-skins (WebSocket + бекфіл search) — {назва: {id лота: ціна}}.

Чиста структура даних без I/O: наповнюють ззовні (WS-події, search-бекфіл),
читають для показу ціни і для відбору ID під купівлю.
"""
from __future__ import annotations


class LisCache:
    def __init__(self) -> None:
        self._lots: dict[str, dict[int, float]] = {}

    def upsert(self, name: str, lot_id: int, price: float) -> None:
        """Додати лот або оновити його ціну (WS: obtained_skin_added / _price_changed)."""
        self._lots.setdefault(name, {})[lot_id] = price

    def remove(self, name: str, lot_id: int) -> None:
        """Прибрати лот (WS: obtained_skin_deleted). Останній лот -> назва зникає з кешу."""
        m = self._lots.get(name)
        if m is None:
            return
        m.pop(lot_id, None)
        if not m:
            del self._lots[name]

    def replace_name(self, name: str, lots: dict) -> None:
        """Повна заміна лотів для назви (бекфіл/періодична звірка через search API)."""
        if lots:
            self._lots[name] = dict(lots)
        else:
            self._lots.pop(name, None)

    def has(self, name: str) -> bool:
        return bool(self._lots.get(name))

    def count(self, name: str) -> int:
        return len(self._lots.get(name, ()))

    def names(self):
        return list(self._lots.keys())

    def best(self, name: str):
        """(id лота, ціна) найдешевшого, або None."""
        m = self._lots.get(name)
        if not m:
            return None
        lot_id = min(m, key=m.get)
        return lot_id, m[lot_id]

    def ids_under(self, name: str, max_price: float, limit: int = 100) -> list:
        """ID лотів з ціною <= max_price, найдешевші перші, максимум `limit`.

        Навмисно НЕ "N найдешевших хай там що" — якщо під стелею лежить лише
        кілька лотів, а решта різко дорожчі (сміттєвий лот + провал у ціні),
        у відбір вони не потраплять. Саме це рубіж, що захищає купівлю від
        випадкового набору задорогих лотів.
        """
        m = self._lots.get(name)
        if not m:
            return []
        eligible = sorted((price, lid) for lid, price in m.items() if price <= max_price)
        return [lid for _, lid in eligible[:limit]]
