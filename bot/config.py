from __future__ import annotations

import os
from dataclasses import dataclass

from dotenv import load_dotenv

# читаємо .env (локально); на Railway змінні йдуть з платформи — load_dotenv просто нічого не робить
load_dotenv()

DEFAULT_EXPORT_URL = "https://lis-skins.com/market_export_json/csgo.json"


@dataclass
class Config:
    telegram_token: str
    db_path: str = "bot.db"
    poll_interval: int = 60
    lis_export_url: str = DEFAULT_EXPORT_URL
    http_timeout: float = 30.0

    @classmethod
    def load(cls) -> "Config":
        token = os.environ.get("TELEGRAM_TOKEN", "").strip()
        if not token:
            raise SystemExit("TELEGRAM_TOKEN не заданий (env)")
        return cls(
            telegram_token=token,
            db_path=os.environ.get("DB_PATH", "bot.db"),
            poll_interval=int(os.environ.get("POLL_INTERVAL", "60")),
            lis_export_url=os.environ.get("LIS_EXPORT_URL", DEFAULT_EXPORT_URL),
            http_timeout=float(os.environ.get("HTTP_TIMEOUT", "30")),
        )
