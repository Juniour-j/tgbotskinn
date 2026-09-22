from bot.lis_search import next_cursor, parse_search_page


def test_parse_search_page_groups_by_name():
    payload = {
        "data": [
            {"id": 125350, "name": "Kilowatt Case", "price": 0.12},
            {"id": 125349, "name": "Kilowatt Case", "price": 0.11},
            {"id": 1, "name": "Fever Case", "price": 0.30},
        ],
        "meta": {"per_page": 200, "next_cursor": "abc"},
    }
    lots = parse_search_page(payload)
    assert lots == {
        "Kilowatt Case": {125350: 0.12, 125349: 0.11},
        "Fever Case": {1: 0.30},
    }


def test_parse_search_page_skips_malformed_rows():
    payload = {"data": [
        {"id": 1, "name": "A", "price": 0.1},
        {"id": None, "name": "B", "price": 0.1},          # немає id
        {"id": 2, "name": "", "price": 0.1},               # порожня назва
        {"id": 3, "name": "C", "price": "not-a-number"},   # погана ціна
        {"id": 4, "name": "D"},                             # ціни нема взагалі
    ]}
    assert parse_search_page(payload) == {"A": {1: 0.1}}


def test_parse_search_page_empty_data():
    assert parse_search_page({"data": []}) == {}
    assert parse_search_page({}) == {}


def test_next_cursor_present():
    assert next_cursor({"meta": {"next_cursor": "xyz", "per_page": 200}}) == "xyz"


def test_next_cursor_absent_returns_none():
    assert next_cursor({"meta": {"per_page": 200}}) is None
    assert next_cursor({}) is None
    assert next_cursor({"meta": {"next_cursor": ""}}) is None
