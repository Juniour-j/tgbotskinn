import pytest

from bot.config import Config

_WEBHOOK_VARS = ("MODE", "WEBHOOK_BASE_URL", "WEBHOOK_SECRET", "WEBAPP_HOST", "WEBAPP_PORT")


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    monkeypatch.setenv("TELEGRAM_TOKEN", "123456:test")
    for k in _WEBHOOK_VARS:
        monkeypatch.delenv(k, raising=False)


def _webhook_env(monkeypatch, **over):
    env = {
        "MODE": "webhook",
        "WEBHOOK_BASE_URL": "https://bot.example.org",
        "WEBHOOK_SECRET": "a1_B2-c3",
        **over,
    }
    for k, v in env.items():
        monkeypatch.setenv(k, v)


def test_default_mode_is_polling_and_needs_no_webhook_settings():
    cfg = Config.load()
    assert cfg.mode == "polling"


def test_webhook_mode_loads_settings(monkeypatch):
    _webhook_env(monkeypatch)
    cfg = Config.load()
    assert cfg.mode == "webhook"
    assert cfg.webhook_url == "https://bot.example.org/webhook"
    assert cfg.webhook_secret == "a1_B2-c3"
    assert (cfg.webapp_host, cfg.webapp_port) == ("127.0.0.1", 8080)


def test_webhook_url_ignores_trailing_slash(monkeypatch):
    _webhook_env(monkeypatch, WEBHOOK_BASE_URL="https://bot.example.org/")
    assert Config.load().webhook_url == "https://bot.example.org/webhook"


def test_secret_of_maximum_length_is_accepted(monkeypatch):
    _webhook_env(monkeypatch, WEBHOOK_SECRET="x" * 256)
    assert Config.load().webhook_secret == "x" * 256


def test_webapp_host_and_port_can_be_overridden(monkeypatch):
    _webhook_env(monkeypatch, WEBAPP_HOST="0.0.0.0", WEBAPP_PORT="9000")
    cfg = Config.load()
    assert (cfg.webapp_host, cfg.webapp_port) == ("0.0.0.0", 9000)


@pytest.mark.parametrize("name,value", [
    ("MODE", "bogus"),
    ("WEBHOOK_BASE_URL", ""),
    ("WEBHOOK_BASE_URL", "http://bot.example.org"),  # Telegram приймає лише https
    ("WEBHOOK_BASE_URL", "https://"),                # без хоста
    ("WEBHOOK_SECRET", ""),
    ("WEBHOOK_SECRET", "bad secret!"),                # дозволено лише A-Za-z0-9_-
    ("WEBHOOK_SECRET", "x" * 257),                    # ліміт Telegram — 256 символів
])
def test_invalid_webhook_settings_exit_naming_the_variable(monkeypatch, name, value):
    _webhook_env(monkeypatch, **{name: value})
    with pytest.raises(SystemExit, match=name):
        Config.load()
