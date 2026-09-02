"""Пошук канонічної назви скіна за приблизним вводом користувача.

Тільки stdlib (difflib) — щоб не тягнути нативні залежності на Railway.
"""
import re
from difflib import SequenceMatcher

_WS = re.compile(r"\s+")

# поріг, з якого приблизний збіг вважаємо надійним
MIN_CONFIDENT = 0.93
# якщо другий за схожістю варіант майже такий самий — вважаємо неоднозначним
AMBIGUOUS_GAP = 0.03
# поріг для показу підказок
MIN_SUGGEST = 0.4


def normalize(s: str) -> str:
    s = s.strip().casefold()
    for ch in ("★", "™", "|"):
        s = s.replace(ch, " ")
    return _WS.sub(" ", s).strip()


def _score(nq: str, nname: str) -> float:
    if not nq or not nname:
        return 0.0
    if nq == nname:
        return 1.0
    ratio = SequenceMatcher(None, nq, nname).ratio()
    if nq in nname:
        ratio = max(ratio, 0.9 + 0.1 * len(nq) / len(nname))
    return ratio


def best_matches(query: str, names, limit: int = 5):
    """Список (name, score), відсортований за спаданням схожості."""
    nq = normalize(query)
    scored = ((n, _score(nq, normalize(n))) for n in names)
    return sorted(scored, key=lambda t: t[1], reverse=True)[:limit]


def resolve(query: str, names):
    """
    (canonical_name, exact) якщо вдалося визначити скін,
    інакше (None, False).
    """
    nq = normalize(query)
    exact = [n for n in names if normalize(n) == nq]
    if len(exact) == 1:
        return exact[0], True

    ranked = best_matches(query, names, 3)
    if not ranked or ranked[0][1] < MIN_CONFIDENT:
        return None, False
    if len(ranked) > 1 and ranked[0][1] - ranked[1][1] < AMBIGUOUS_GAP:
        return None, False
    return ranked[0][0], False
