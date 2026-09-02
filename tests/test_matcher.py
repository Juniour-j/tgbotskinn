from bot import matcher

NAMES = [
    "AWP | Asiimov (Field-Tested)",
    "AWP | Asiimov (Battle-Scarred)",
    "AK-47 | Redline (Field-Tested)",
    "Glock-18 | Fade (Factory New)",
    "★ Karambit | Doppler (Factory New)",
]


def test_exact_ignores_case_and_pipes():
    name, exact = matcher.resolve("awp asiimov (field-tested)", NAMES)
    assert name == "AWP | Asiimov (Field-Tested)"
    assert exact is True


def test_typo_resolves_fuzzy():
    name, exact = matcher.resolve("AWP | Asimov (Field-Tested)", NAMES)
    assert name == "AWP | Asiimov (Field-Tested)"
    assert exact is False


def test_ambiguous_wear_returns_none():
    # без вказаного стану — не вгадуємо між FT і BS
    name, _ = matcher.resolve("awp asiimov", NAMES)
    assert name is None


def test_garbage_returns_none():
    name, _ = matcher.resolve("zzz totally unknown skin", NAMES)
    assert name is None


def test_best_matches_ranks_relevant_first():
    hits = [n for n, _ in matcher.best_matches("redline field-tested", NAMES, 3)]
    assert hits[0] == "AK-47 | Redline (Field-Tested)"


def test_star_prefix_is_normalized_away():
    name, exact = matcher.resolve("karambit doppler (factory new)", NAMES)
    assert name == "★ Karambit | Doppler (Factory New)"
    assert exact is True
