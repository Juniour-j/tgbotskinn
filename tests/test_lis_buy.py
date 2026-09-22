from bot.lis_buy import parse_trade_url


def test_parse_trade_url_full_link():
    url = "https://steamcommunity.com/tradeoffer/new/?partner=123456789&token=AbC-dEf_Gh1"
    assert parse_trade_url(url) == ("123456789", "AbC-dEf_Gh1")


def test_parse_trade_url_order_independent_and_extra_params():
    url = "token=XyZ9&partner=42&other=1"
    assert parse_trade_url(url) == ("42", "XyZ9")


def test_parse_trade_url_strips_whitespace():
    url = "  https://steamcommunity.com/tradeoffer/new/?partner=1&token=T  \n"
    assert parse_trade_url(url) == ("1", "T")


def test_parse_trade_url_missing_token_is_none():
    assert parse_trade_url("partner=42") is None


def test_parse_trade_url_missing_partner_is_none():
    assert parse_trade_url("token=abc") is None


def test_parse_trade_url_garbage_is_none():
    assert parse_trade_url("я не трейд лінк") is None
    assert parse_trade_url("") is None
