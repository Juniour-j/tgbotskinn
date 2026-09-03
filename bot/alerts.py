"""Чиста логіка рішення про сповіщення. Без I/O — легко тестується."""
from __future__ import annotations


def hit(target: float, current: float, direction: str = "down") -> bool:
    """Чи виконана умова ціни зараз."""
    if direction == "up":
        return current >= target
    return current <= target


def evaluate(target: float, triggered: bool, current, direction: str = "down") -> str:
    """
    "fire"  — умова вперше виконана, сповіщаємо;
    "rearm" — після спрацювання умова знову НЕ виконана, знімаємо прапорець;
    "none"  — нічого.
    """
    if current is None:
        return "none"
    ok = hit(target, current, direction)
    if not triggered and ok:
        return "fire"
    if triggered and not ok:
        return "rearm"
    return "none"
