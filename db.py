import json
import sqlite3
import threading

DB_PATH = "games.db"
_local = threading.local()


def _conn() -> sqlite3.Connection:
    """Thread-local connection."""
    if not hasattr(_local, "conn"):
        _local.conn = sqlite3.connect(DB_PATH)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
    return _local.conn


def init():
    conn = _conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS games (
            channel TEXT PRIMARY KEY,
            data TEXT NOT NULL
        )
    """)
    conn.commit()


def save(channel: str, data: dict):
    conn = _conn()
    conn.execute(
        "INSERT OR REPLACE INTO games (channel, data) VALUES (?, ?)",
        (channel, json.dumps(data, ensure_ascii=False)),
    )
    conn.commit()


def load_all() -> dict[str, dict]:
    conn = _conn()
    rows = conn.execute("SELECT channel, data FROM games").fetchall()
    return {row["channel"]: json.loads(row["data"]) for row in rows}


def delete(channel: str):
    conn = _conn()
    conn.execute("DELETE FROM games WHERE channel = ?", (channel,))
    conn.commit()
