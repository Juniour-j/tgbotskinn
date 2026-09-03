"""SQLite-сховище стежень (aiosqlite). Одне довге зʼєднання на процес."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import aiosqlite

_db: aiosqlite.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS watches (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id      INTEGER NOT NULL,
    chat_id      INTEGER NOT NULL,
    game         TEXT    NOT NULL DEFAULT 'csgo',
    skin_name    TEXT    NOT NULL,
    target_price REAL    NOT NULL,
    direction    TEXT    NOT NULL DEFAULT 'down',
    min_qty      INTEGER NOT NULL DEFAULT 1,
    muted        INTEGER NOT NULL DEFAULT 0,
    muted_until  TEXT,
    triggered    INTEGER NOT NULL DEFAULT 0,
    last_price   REAL,
    created_at   TEXT    NOT NULL,
    notified_at  TEXT
);
CREATE INDEX IF NOT EXISTS idx_watches_user ON watches(user_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_watches_uniq
    ON watches(user_id, game, skin_name, target_price);
"""

# прості міграції для БД, створених ранішими версіями
_MIGRATIONS = [
    "ALTER TABLE watches ADD COLUMN min_qty INTEGER NOT NULL DEFAULT 1",
    "ALTER TABLE watches ADD COLUMN direction TEXT NOT NULL DEFAULT 'down'",
    "ALTER TABLE watches ADD COLUMN muted_until TEXT",
]


def _now_dt() -> datetime:
    return datetime.now(timezone.utc)


def _now() -> str:
    return _now_dt().isoformat(timespec="seconds")


def is_muted(row) -> bool:
    if row["muted"]:
        return True
    mu = row["muted_until"]
    if mu:
        try:
            return datetime.fromisoformat(mu) > _now_dt()
        except ValueError:
            return False
    return False


def muted_label(row) -> str:
    """'' | '🔕 назавжди' | '🔕 ще 45 хв' | '🔕 ще 6 год'."""
    if row["muted"]:
        return "🔕 назавжди"
    mu = row["muted_until"]
    if not mu:
        return ""
    try:
        dt = datetime.fromisoformat(mu)
    except ValueError:
        return ""
    mins = (dt - _now_dt()).total_seconds() / 60
    if mins <= 0:
        return ""
    if mins > 90:
        return f"🔕 ще {int(mins / 60)} год"
    return f"🔕 ще {int(mins)} хв"


async def init_db(path: str):
    global _db
    _db = await aiosqlite.connect(path)
    _db.row_factory = aiosqlite.Row
    await _db.execute("PRAGMA journal_mode=WAL")
    await _db.executescript(SCHEMA)
    for stmt in _MIGRATIONS:
        try:
            await _db.execute(stmt)
        except aiosqlite.OperationalError:
            pass  # колонка вже є
    await _db.commit()


async def close():
    if _db is not None:
        await _db.close()


async def add_watch(user_id: int, chat_id: int, skin_name: str, target_price: float,
                    game: str = "csgo", min_qty: int = 1, direction: str = "down"):
    """(id, "created"|"updated")."""
    try:
        cur = await _db.execute(
            "INSERT INTO watches(user_id, chat_id, game, skin_name, target_price, "
            "direction, min_qty, created_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (user_id, chat_id, game, skin_name, target_price, direction, min_qty, _now()),
        )
        await _db.commit()
        return cur.lastrowid, "created"
    except aiosqlite.IntegrityError:
        await _db.execute(
            "UPDATE watches SET direction=?, min_qty=?, triggered=0, muted=0, muted_until=NULL "
            "WHERE user_id=? AND game=? AND skin_name=? AND target_price=?",
            (direction, min_qty, user_id, game, skin_name, target_price),
        )
        await _db.commit()
        cur = await _db.execute(
            "SELECT id FROM watches WHERE user_id=? AND game=? AND skin_name=? AND target_price=?",
            (user_id, game, skin_name, target_price),
        )
        row = await cur.fetchone()
        return (row["id"] if row else None), "updated"


async def list_watches(user_id: int):
    cur = await _db.execute(
        "SELECT * FROM watches WHERE user_id=? ORDER BY id", (user_id,)
    )
    return await cur.fetchall()


async def get_watch(user_id: int, watch_id: int):
    cur = await _db.execute(
        "SELECT * FROM watches WHERE user_id=? AND id=?", (user_id, watch_id)
    )
    return await cur.fetchone()


async def remove_watch(user_id: int, watch_id: int) -> bool:
    cur = await _db.execute(
        "DELETE FROM watches WHERE user_id=? AND id=?", (user_id, watch_id)
    )
    await _db.commit()
    return cur.rowcount > 0


async def remove_triggered(user_id: int) -> int:
    cur = await _db.execute(
        "DELETE FROM watches WHERE user_id=? AND triggered=1", (user_id,)
    )
    await _db.commit()
    return cur.rowcount


async def mute_all(user_id: int, muted: bool) -> int:
    cur = await _db.execute(
        "UPDATE watches SET muted=?, muted_until=NULL WHERE user_id=?",
        (1 if muted else 0, user_id),
    )
    await _db.commit()
    return cur.rowcount


async def set_target(user_id: int, watch_id: int, price: float, min_qty: int = 1,
                     direction: str = "down") -> bool:
    cur = await _db.execute(
        "UPDATE watches SET target_price=?, min_qty=?, direction=?, triggered=0 "
        "WHERE user_id=? AND id=?",
        (price, min_qty, direction, user_id, watch_id),
    )
    await _db.commit()
    return cur.rowcount > 0


async def set_muted(user_id: int, watch_id: int, muted: bool) -> bool:
    cur = await _db.execute(
        "UPDATE watches SET muted=?, muted_until=NULL WHERE user_id=? AND id=?",
        (1 if muted else 0, user_id, watch_id),
    )
    await _db.commit()
    return cur.rowcount > 0


async def snooze(user_id: int, watch_id: int, minutes: int) -> bool:
    until = (_now_dt() + timedelta(minutes=minutes)).isoformat(timespec="seconds")
    cur = await _db.execute(
        "UPDATE watches SET muted=0, muted_until=? WHERE user_id=? AND id=?",
        (until, user_id, watch_id),
    )
    await _db.commit()
    return cur.rowcount > 0


async def all_watches():
    cur = await _db.execute("SELECT * FROM watches")
    return await cur.fetchall()


async def count_watches() -> int:
    cur = await _db.execute("SELECT COUNT(*) AS c FROM watches")
    row = await cur.fetchone()
    return row["c"] if row else 0


async def watched_names() -> set:
    """Усі унікальні назви скінів зі стежень (для індексу глибини/цін)."""
    cur = await _db.execute("SELECT DISTINCT skin_name FROM watches")
    return {r["skin_name"] for r in await cur.fetchall()}


async def mark_triggered(watch_id: int, price: float | None, triggered: bool):
    await _db.execute(
        "UPDATE watches SET last_price=?, triggered=?, notified_at=? WHERE id=?",
        (price, 1 if triggered else 0, _now() if triggered else None, watch_id),
    )
    await _db.commit()


async def set_last_price(watch_id: int, price: float):
    await _db.execute(
        "UPDATE watches SET last_price=? WHERE id=?", (price, watch_id)
    )
    await _db.commit()
