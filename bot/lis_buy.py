"""Купівля через lis-skins API (`/user/balance`, згодом `/market/buy`) —
особистий ключ на людину, окремий від спільного ключа сканування (LIS_API_KEY):
гроші й Steam-акаунт завжди чиїсь конкретні, тому не змішуємо з живим кешем.
"""
from __future__ import annotations

import re

import httpx

BALANCE_URL = "https://api.lis-skins.com/v1/user/balance"

_PARTNER_RE = re.compile(r"partner=(\d+)")
_TOKEN_RE = re.compile(r"token=([A-Za-z0-9_-]+)")


def parse_trade_url(text: str):
    """Витягує (partner, token) з повного Trade URL або будь-якого рядка,
    де вони є як query-параметри. None, якщо не схоже на Trade URL."""
    text = (text or "").strip()
    m_partner = _PARTNER_RE.search(text)
    m_token = _TOKEN_RE.search(text)
    if not (m_partner and m_token):
        return None
    return m_partner.group(1), m_token.group(1)


class LisBuyClient:
    """Мережевий шар навмисно тонкий, без юніт-тестів (як LisClient/DepthIndex) —
    перевіряється живим ключем на сервері."""

    def __init__(self, timeout: float = 15.0):
        self._http = httpx.AsyncClient(timeout=timeout)

    async def get_balance(self, api_key: str) -> float:
        """Баланс користувача цього ключа. Кидає httpx.HTTPStatusError,
        якщо ключ невалідний (401/403) чи інша помилка API."""
        resp = await self._http.get(BALANCE_URL, headers={
            "Authorization": f"Bearer {api_key}", "Accept": "application/json"})
        resp.raise_for_status()
        return float(resp.json()["data"]["balance"])

    async def aclose(self) -> None:
        await self._http.aclose()
