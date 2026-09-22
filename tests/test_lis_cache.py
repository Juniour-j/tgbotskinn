from bot.lis_cache import LisCache


def test_best_on_empty_returns_none():
    c = LisCache()
    assert c.best("Kilowatt Case") is None
    assert c.has("Kilowatt Case") is False
    assert c.count("Kilowatt Case") == 0


def test_upsert_and_best_returns_cheapest():
    c = LisCache()
    c.upsert("Kilowatt Case", 1, 0.20)
    c.upsert("Kilowatt Case", 2, 0.11)
    c.upsert("Kilowatt Case", 3, 0.15)
    assert c.best("Kilowatt Case") == (2, 0.11)
    assert c.count("Kilowatt Case") == 3
    assert c.has("Kilowatt Case") is True


def test_upsert_same_id_updates_price():
    c = LisCache()
    c.upsert("Kilowatt Case", 1, 0.20)
    c.upsert("Kilowatt Case", 1, 0.09)
    assert c.best("Kilowatt Case") == (1, 0.09)
    assert c.count("Kilowatt Case") == 1


def test_remove_lot():
    c = LisCache()
    c.upsert("Kilowatt Case", 1, 0.11)
    c.upsert("Kilowatt Case", 2, 0.20)
    c.remove("Kilowatt Case", 1)
    assert c.best("Kilowatt Case") == (2, 0.20)


def test_remove_last_lot_clears_name():
    c = LisCache()
    c.upsert("Kilowatt Case", 1, 0.11)
    c.remove("Kilowatt Case", 1)
    assert c.has("Kilowatt Case") is False
    assert c.best("Kilowatt Case") is None


def test_remove_unknown_is_noop():
    c = LisCache()
    c.remove("Nope", 1)  # не мало кидати виняток
    c.upsert("Kilowatt Case", 1, 0.11)
    c.remove("Kilowatt Case", 999)
    assert c.count("Kilowatt Case") == 1


def test_replace_name_full_backfill():
    c = LisCache()
    c.upsert("Kilowatt Case", 1, 0.50)  # застаріле, має бути стерте
    c.replace_name("Kilowatt Case", {2: 0.11, 3: 0.13})
    assert c.count("Kilowatt Case") == 2
    assert c.best("Kilowatt Case") == (2, 0.11)


def test_replace_name_with_empty_clears_it():
    c = LisCache()
    c.upsert("Kilowatt Case", 1, 0.11)
    c.replace_name("Kilowatt Case", {})
    assert c.has("Kilowatt Case") is False


def test_ids_under_price_ceiling_skips_expensive_gap():
    # саме той сценарій: 1 лот-пил за $0.19, решта одразу $200+ -- не мусить туди лізти
    c = LisCache()
    c.upsert("Item", 1, 0.19)
    c.upsert("Item", 2, 200.0)
    c.upsert("Item", 3, 0.21)
    c.upsert("Item", 4, 0.20)
    ids = c.ids_under("Item", max_price=0.25, limit=100)
    assert ids == [1, 4, 3]  # відсортовані за ціною, найдешевші перші
    assert 2 not in ids


def test_ids_under_respects_limit():
    c = LisCache()
    for i, price in enumerate([0.10, 0.11, 0.12, 0.13, 0.14], start=1):
        c.upsert("Item", i, price)
    ids = c.ids_under("Item", max_price=1.0, limit=3)
    assert ids == [1, 2, 3]


def test_ids_under_unknown_name_returns_empty():
    c = LisCache()
    assert c.ids_under("Nope", max_price=100) == []


def test_names_lists_tracked_names():
    c = LisCache()
    c.upsert("A", 1, 0.1)
    c.upsert("B", 2, 0.2)
    assert set(c.names()) == {"A", "B"}
