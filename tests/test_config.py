import os

from bot.config import Config


def _clear(monkeypatch):
    for k in ("TELEGRAM_TOKEN", "LIS_API_KEY", "SECRETS_KEY"):
        monkeypatch.delenv(k, raising=False)


def test_lis_api_key_defaults_to_none(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TELEGRAM_TOKEN", "t")
    cfg = Config.load()
    assert cfg.lis_api_key is None


def test_lis_api_key_blank_is_none(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TELEGRAM_TOKEN", "t")
    monkeypatch.setenv("LIS_API_KEY", "   ")
    cfg = Config.load()
    assert cfg.lis_api_key is None


def test_lis_api_key_set(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TELEGRAM_TOKEN", "t")
    monkeypatch.setenv("LIS_API_KEY", "secret123")
    cfg = Config.load()
    assert cfg.lis_api_key == "secret123"


def test_secrets_key_defaults_to_none(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TELEGRAM_TOKEN", "t")
    cfg = Config.load()
    assert cfg.secrets_key is None


def test_secrets_key_set(monkeypatch):
    _clear(monkeypatch)
    monkeypatch.setenv("TELEGRAM_TOKEN", "t")
    monkeypatch.setenv("SECRETS_KEY", "fernetkey123")
    cfg = Config.load()
    assert cfg.secrets_key == "fernetkey123"
