import pytest
from cryptography.fernet import Fernet, InvalidToken

from bot.crypto_store import decrypt, encrypt


def _key() -> str:
    return Fernet.generate_key().decode()


def test_roundtrip():
    key = _key()
    payload = {"api_key": "abc123", "partner": "111", "token": "tOk"}
    blob = encrypt(key, payload)
    assert isinstance(blob, bytes)
    assert decrypt(key, blob) == payload


def test_wrong_server_key_fails_to_decrypt():
    blob = encrypt(_key(), {"api_key": "abc"})
    with pytest.raises(InvalidToken):
        decrypt(_key(), blob)


def test_tampered_blob_fails_to_decrypt():
    key = _key()
    blob = encrypt(key, {"api_key": "abc"})
    tampered = blob[:-1] + (b"0" if blob[-1:] != b"0" else b"1")
    with pytest.raises(InvalidToken):
        decrypt(key, tampered)
