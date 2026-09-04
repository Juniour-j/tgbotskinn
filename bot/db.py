"""SQLite-сховище (aiosqlite). Одне довге зʼєднання на процес."""
from __future__ import annotations

import time
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

CREATE TABLE IF NOT EXISTS price_hist (
    name  TEXT    NOT NULL,
    hour  INTEGER NOT NULL,
    price REAL    NOT NULL,
    PRIMARY KEY (name, hour)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS holdings (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id   INTEGER NOT NULL,
    skin_name TEXT    NOT NULL,
    qty       INTEGER NOT NULL,
    buy_price REAL    NOT NULL,
    bought_at TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_holdings_user ON holdings(user_id);
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
        return f"🔕 ще {round(mins / 60)} год"
    return f"🔕 ще {max(1, round(mins))} хв"


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


# ---------- історія цін ----------

async def record_prices(pairs) -> None:
    """pairs: iterable (name, price). Погодинний знімок (upsert у межах години)."""
    hour = int(time.time() // 3600)
    rows = [(n, hour, float(p)) for n, p in pairs if p is not None]
    if rows:
        await _db.executemany(
            "INSERT OR REPLACE INTO price_hist(name, hour, price) VALUES (?, ?, ?)", rows)
        await _db.commit()


async def prune_prices(keep_days: int = 70) -> int:
    cutoff = int(time.time() // 3600) - keep_days * 24
    cur = await _db.execute("DELETE FROM price_hist WHERE hour < ?", (cutoff,))
    await _db.commit()
    return cur.rowcount


async def price_series(name: str, hours: int):
    since = int(time.time() // 3600) - hours
    cur = await _db.execute(
        "SELECT hour, price FROM price_hist WHERE name=? AND hour>=? ORDER BY hour",
        (name, since),
    )
    return [(r["hour"], r["price"]) for r in await cur.fetchall()]


async def price_series_bulk(names, hours: int) -> dict:
    """{name: [(hour, price), ...]} одним запитом — для тренду в списку."""
    names = list(dict.fromkeys(names))
    if not names:
        return {}
    since = int(time.time() // 3600) - hours
    ph = ",".join("?" * len(names))
    cur = await _db.execute(
        f"SELECT name, hour, price FROM price_hist "
        f"WHERE hour>=? AND name IN ({ph}) ORDER BY name, hour",
        (since, *names),
    )
    out: dict[str, list] = {}
    for r in await cur.fetchall():
        out.setdefault(r["name"], []).append((r["hour"], r["price"]))
    return out


# ---------- портфель ----------

async def add_holding(user_id: int, name: str, qty: int, price: float) -> int:
    cur = await _db.execute(
        "INSERT INTO holdings(user_id, skin_name, qty, buy_price, bought_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (user_id, name, qty, price, _now()),
    )
    await _db.commit()
    return cur.lastrowid


async def list_holdings(user_id: int):
    cur = await _db.execute(
        "SELECT * FROM holdings WHERE user_id=? ORDER BY skin_name, id", (user_id,)
    )
    return await cur.fetchall()


async def get_holding(user_id: int, hid: int):
    cur = await _db.execute(
        "SELECT * FROM holdings WHERE user_id=? AND id=?", (user_id, hid)
    )
    return await cur.fetchone()


async def reduce_holding(user_id: int, hid: int, qty: int) -> bool:
    """Продати qty шт з позиції: зменшити або видалити."""
    row = await get_holding(user_id, hid)
    if row is None:
        return False
    if qty >= row["qty"]:
        await _db.execute("DELETE FROM holdings WHERE id=?", (hid,))
    else:
        await _db.execute("UPDATE holdings SET qty=qty-? WHERE id=?", (qty, hid))
    await _db.commit()
    return True


async def remove_holding(user_id: int, hid: int) -> bool:
    cur = await _db.execute(
        "DELETE FROM holdings WHERE user_id=? AND id=?", (user_id, hid)
    )
    await _db.commit()
    return cur.rowcount > 0
