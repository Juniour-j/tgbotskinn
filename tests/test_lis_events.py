from bot.lis_events import parse_market_event


def test_added_event_is_upsert():
    data = {"id": 125345, "name": "Kilowatt Case", "price": 0.11, "event": "obtained_skin_added"}
    assert parse_market_event(data) == ("upsert", "Kilowatt Case", 125345, 0.11)


def test_price_changed_event_is_upsert():
    data = {"id": 1, "name": "FAMAS | Doomkitty (Minimal Wear)", "price": 109.65,
            "event": "obtained_skin_price_changed"}
    assert parse_market_event(data) == ("upsert", "FAMAS | Doomkitty (Minimal Wear)", 1, 109.65)


def test_deleted_event_is_remove_regardless_of_price_field():
    # приклад із документації lis-skins: у deleted теж є ціна в payload, ми її ігноруємо
    data = {"id": 1, "name": "FAMAS | Doomkitty (Minimal Wear)", "price": 109.65,
            "item_float": "0.276466548442841", "event": "obtained_skin_deleted"}
    assert parse_market_event(data) == ("remove", "FAMAS | Doomkitty (Minimal Wear)", 1, None)


def test_unknown_event_type_returns_none():
    data = {"id": 1, "name": "X", "price": 1.0, "event": "something_else"}
    assert parse_market_event(data) is None


def test_missing_required_field_returns_none():
    assert parse_market_event({"name": "X", "price": 1.0, "event": "obtained_skin_added"}) is None
    assert parse_market_event({"id": 1, "price": 1.0, "event": "obtained_skin_added"}) is None
    assert parse_market_event({"id": "not-an-int", "name": "X", "price": 1.0,
                               "event": "obtained_skin_added"}) is None


def test_upsert_without_price_returns_none():
    assert parse_market_event({"id": 1, "name": "X", "event": "obtained_skin_added"}) is None
