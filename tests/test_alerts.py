from bot.alerts import evaluate


def test_fire_on_reaching_target():
    assert evaluate(50.0, False, 49.99) == "fire"
    assert evaluate(50.0, False, 50.0) == "fire"


def test_no_fire_above_target():
    assert evaluate(50.0, False, 50.01) == "none"


def test_no_double_fire():
    assert evaluate(50.0, True, 40.0) == "none"


def test_rearm_when_back_above_target():
    assert evaluate(50.0, True, 55.0) == "rearm"


def test_missing_price_is_noop():
    assert evaluate(50.0, False, None) == "none"
    assert evaluate(50.0, True, None) == "none"


def test_direction_up():
    assert evaluate(50.0, False, 55.0, "up") == "fire"
    assert evaluate(50.0, False, 49.0, "up") == "none"
    assert evaluate(50.0, True, 49.0, "up") == "rearm"
