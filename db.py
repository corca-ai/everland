import json
import sqlite3
import threading


class GameDB:
    """게임별 독립 SQLite 저장소."""

    def __init__(self, path: str):
        self._path = path
        self._local = threading.local()
        self._init()

    def _conn(self) -> sqlite3.Connection:
        if not hasattr(self._local, "conn"):
            self._local.conn = sqlite3.connect(self._path)
            self._local.conn.row_factory = sqlite3.Row
            self._local.conn.execute("PRAGMA journal_mode=WAL")
        return self._local.conn

    def _init(self):
        conn = self._conn()
        conn.execute("""
            CREATE TABLE IF NOT EXISTS games (
                channel TEXT PRIMARY KEY,
                data TEXT NOT NULL
            )
        """)
        conn.commit()

    def save(self, channel: str, data: dict):
        conn = self._conn()
        conn.execute(
            "INSERT OR REPLACE INTO games (channel, data) VALUES (?, ?)",
            (channel, json.dumps(data, ensure_ascii=False)),
        )
        conn.commit()

    def load_all(self) -> dict[str, dict]:
        conn = self._conn()
        rows = conn.execute("SELECT channel, data FROM games").fetchall()
        return {row["channel"]: json.loads(row["data"]) for row in rows}

    def delete(self, channel: str):
        conn = self._conn()
        conn.execute("DELETE FROM games WHERE channel = ?", (channel,))
        conn.commit()
