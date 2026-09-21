from __future__ import annotations

import os
import re
from dataclasses import dataclass
from urllib.parse import urlparse

from dotenv import load_dotenv

# читаємо .env (локально); на Railway змінні йдуть з платформи — load_dotenv просто нічого не робить
load_dotenv()

DEFAULT_EXPORT_URL = "https://lis-skins.com/market_export_json/csgo.json"
DEFAULT_FULL_EXPORT_URL = "https://lis-skins.com/market_export_json/api_csgo_full.json"
DEFAULT_MCSGO_URL = "https://market.csgo.com/api/v2/prices/class_instance/USD.json"
DEFAULT_SKINPORT_URL = "https://api.skinport.com/v1/items?app_id=730&currency=USD"

WEBHOOK_PATH = "/webhook"
_MODES = ("polling", "webhook")
# secret_token у Telegram: 1–256 символів, лише A-Z a-z 0-9 _ -
_SECRET_RE = re.compile(r"[A-Za-z0-9_-]{1,256}")


def _parse_ids(raw: str) -> frozenset[int]:
    out = set()
    for chunk in raw.replace(",", " ").split():
        try:
            out.add(int(chunk))
        except ValueError:
            continue
    return frozenset(out)


def _parse_sources(raw: str) -> tuple:
    known = ("mcsgo", "skinport")
    return tuple(s for s in raw.replace(",", " ").split() if s in known)


@dataclass
class Config:
    telegram_token: str
    db_path: str = "bot.db"
    poll_interval: int = 60
    lis_export_url: str = DEFAULT_EXPORT_URL
    full_export_url: str = DEFAULT_FULL_EXPORT_URL
    depth_refresh_min: int = 10
    http_timeout: float = 30.0
    allowed_user_ids: frozenset[int] = frozenset()
    sources: tuple = ("mcsgo", "skinport")
    mcsgo_url: str = DEFAULT_MCSGO_URL
    skinport_url: str = DEFAULT_SKINPORT_URL
    steam_enabled: bool = True
    mode: str = "polling"
    webhook_base_url: str = ""
    webhook_secret: str = ""
    webapp_host: str = "127.0.0.1"
    webapp_port: int = 8080

    @property
    def webhook_url(self) -> str:
        return self.webhook_base_url.rstrip("/") + WEBHOOK_PATH

    @classmethod
    def load(cls) -> "Config":
        token = os.environ.get("TELEGRAM_TOKEN", "").strip()
        if not token:
            raise SystemExit("TELEGRAM_TOKEN не заданий (env)")
        mode = os.environ.get("MODE", "polling")
        if mode not in _MODES:
            raise SystemExit(f"MODE має бути одним із: {', '.join(_MODES)} (зараз {mode!r})")
        base_url = os.environ.get("WEBHOOK_BASE_URL", "").strip()
        secret = os.environ.get("WEBHOOK_SECRET", "").strip()
        if mode == "webhook":
            parsed = urlparse(base_url)
            if parsed.scheme != "https" or not parsed.netloc:
                raise SystemExit("WEBHOOK_BASE_URL має бути https://<домен> (Telegram приймає лише https)")
            if not _SECRET_RE.fullmatch(secret):
                raise SystemExit("WEBHOOK_SECRET не заданий або має недопустимі символи "
                                 "(1–256 символів: A-Z a-z 0-9 _ -)")
        return cls(
            telegram_token=token,
            db_path=os.environ.get("DB_PATH", "bot.db"),
            poll_interval=int(os.environ.get("POLL_INTERVAL", "60")),
            lis_export_url=os.environ.get("LIS_EXPORT_URL", DEFAULT_EXPORT_URL),
            full_export_url=os.environ.get("FULL_EXPORT_URL", DEFAULT_FULL_EXPORT_URL),
            depth_refresh_min=int(os.environ.get("DEPTH_REFRESH_MIN", "10")),
            http_timeout=float(os.environ.get("HTTP_TIMEOUT", "30")),
            allowed_user_ids=_parse_ids(os.environ.get("ALLOWED_USER_IDS", "")),
            sources=_parse_sources(os.environ.get("SOURCES", "mcsgo,skinport")),
            mcsgo_url=os.environ.get("MCSGO_URL", DEFAULT_MCSGO_URL),
            skinport_url=os.environ.get("SKINPORT_URL", DEFAULT_SKINPORT_URL),
            steam_enabled=os.environ.get("STEAM_ENABLED", "1") not in ("0", "false", ""),
            mode=mode,
            webhook_base_url=base_url,
            webhook_secret=secret,
            webapp_host=os.environ.get("WEBAPP_HOST", "127.0.0.1"),
            webapp_port=int(os.environ.get("WEBAPP_PORT", "8080")),
        )
