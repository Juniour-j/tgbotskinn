"""Аналіз історії цін — чисті функції, без I/O."""
from __future__ import annotations

_BLOCKS = "▁▂▃▄▅▆▇█"


def sparkline(values, width: int = 24) -> str:
    """Юнікод-спарклайн. values — числа за зростанням часу."""
    vals = [v for v in values if v is not None]
    if len(vals) < 2:
        return ""
    if len(vals) > width:  # прорідити рівномірно
        step = len(vals) / width
        vals = [vals[int(i * step)] for i in range(width)]
    lo, hi = min(vals), max(vals)
    if hi == lo:
        return _BLOCKS[3] * len(vals)
    span = hi - lo
    return "".join(_BLOCKS[min(7, int((v - lo) / span * 7 + 0.5))] for v in vals)


def stats(series):
    """series: [(hour, price)]. -> dict або None."""
    if not series:
        return None
    prices = [p for _, p in series]
    return {
        "lo": min(prices),
        "hi": max(prices),
        "avg": sum(prices) / len(prices),
        "first": prices[0],
        "last": prices[-1],
        "n": len(prices),
    }


def change_pct(series) -> float | None:
    """Зміна ціни від початку періоду до кінця, у %."""
    if len(series) < 2:
        return None
    first, last = series[0][1], series[-1][1]
    if first <= 0:
        return None
    return (last - first) / first * 100


def cheaper_than_pct(series, current: float) -> float | None:
    """Яка частка минулих цін БУЛА ВИЩОЮ за поточну (=зараз вигідніше, ніж X% часу)."""
    prices = [p for _, p in series]
    if len(prices) < 5:
        return None
    higher = sum(1 for p in prices if p > current)
    return higher / len(prices) * 100
