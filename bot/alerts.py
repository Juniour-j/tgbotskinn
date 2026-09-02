"""Чиста логіка рішення про сповіщення. Без I/O — легко тестується."""
from __future__ import annotations


def evaluate(target: float, triggered: bool, current: float | None) -> str:
    """
    Повертає:
      "fire"  — ціна вперше досягла цілі, треба сповістити;
      "rearm" — після спрацювання ціна знову вище цілі, знімаємо прапорець;
      "none"  — нічого не робимо.
    """
    if current is None:
        return "none"
    if not triggered and current <= target:
        return "fire"
    if triggered and current > target:
        return "rearm"
    return "none"
