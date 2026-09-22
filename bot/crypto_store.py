"""Шифрування особистих ключів купівлі (lis-skins API key + Trade URL) у БД.

Fernet (AES128-CBC + HMAC, симетричне) з ключем сервера (env SECRETS_KEY).
Без SECRETS_KEY зберігати ключі купівлі не можна — /setkey відмовляє
(bot/handlers.py), а не тримає їх у БД відкритим текстом.
"""
from __future__ import annotations

import json

from cryptography.fernet import Fernet


def encrypt(secret_key: str, payload: dict) -> bytes:
    return Fernet(secret_key.encode()).encrypt(json.dumps(payload).encode())


def decrypt(secret_key: str, blob: bytes) -> dict:
    """cryptography.fernet.InvalidToken, якщо SECRETS_KEY змінився чи дані пошкоджені."""
    return json.loads(Fernet(secret_key.encode()).decrypt(blob).decode())
