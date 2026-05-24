"""
src/database/db.py
Fix #9 — Persistent query history per user
Fix #3 — URL page cache with TTL
Schema:
  users         → id, username, email, password_hash, created_at
  queries       → id, user_id, session_id, question, answer, context_preview,
                   confidence, intent, timestamp
  url_cache     → url_hash, url, text, cached_at
  comparisons   → id, user_id, urls_json, question, results_json, timestamp
"""

import sqlite3
import time
import logging
from pathlib import Path
from contextlib import contextmanager

logger = logging.getLogger(__name__)

DB_PATH           = Path("data") / "ecom_qa.db"
CACHE_TTL_SECONDS = 60 * 60 * 6   # 6 hours
import hashlib


def _url_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()[:32]


class Database:
    def __init__(self, path: Path = DB_PATH):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(str(self.path))
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    # ── Schema ────────────────────────────────────────────────────────────────
    def init_tables(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS users (
                    id            INTEGER PRIMARY KEY AUTOINCREMENT,
                    username      TEXT    UNIQUE NOT NULL,
                    email         TEXT    DEFAULT '',
                    password_hash TEXT    NOT NULL,
                    created_at    REAL    DEFAULT (strftime('%s','now'))
                );

                CREATE TABLE IF NOT EXISTS queries (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id         INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    session_id      TEXT,
                    question        TEXT    NOT NULL,
                    answer          TEXT    DEFAULT '',
                    context_preview TEXT    DEFAULT '',
                    confidence      REAL,
                    intent          TEXT    DEFAULT 'factual',
                    timestamp       REAL    DEFAULT (strftime('%s','now'))
                );

                CREATE TABLE IF NOT EXISTS url_cache (
                    url_hash  TEXT PRIMARY KEY,
                    url       TEXT NOT NULL,
                    text      TEXT NOT NULL,
                    cached_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS comparisons (
                    id           INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id      INTEGER REFERENCES users(id) ON DELETE CASCADE,
                    urls_json    TEXT    NOT NULL,
                    question     TEXT    NOT NULL,
                    results_json TEXT,
                    timestamp    REAL    DEFAULT (strftime('%s','now'))
                );

                CREATE INDEX IF NOT EXISTS idx_queries_user ON queries(user_id);
                CREATE INDEX IF NOT EXISTS idx_queries_session ON queries(session_id);
                CREATE INDEX IF NOT EXISTS idx_cache_hash ON url_cache(url_hash);
            """)
        logger.info("Database initialised at %s", self.path)

    # ── User CRUD ─────────────────────────────────────────────────────────────
    def create_user(self, username: str, email: str, password_hash: str) -> int:
        with self._conn() as conn:
            cur = conn.execute(
                "INSERT INTO users (username, email, password_hash) VALUES (?,?,?)",
                (username, email, password_hash),
            )
            return cur.lastrowid

    def get_user_by_username(self, username: str) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE username = ?", (username,)
            ).fetchone()
            return dict(row) if row else None

    def get_user_by_id(self, user_id: int) -> dict | None:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM users WHERE id = ?", (user_id,)
            ).fetchone()
            return dict(row) if row else None

    # ── Query history ─────────────────────────────────────────────────────────
    def save_query(self, user_id, session_id, question, answer,
                   context_preview="", confidence=None, intent="factual"):
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO queries
                   (user_id, session_id, question, answer, context_preview, confidence, intent)
                   VALUES (?,?,?,?,?,?,?)""",
                (user_id, session_id, question, answer, context_preview, confidence, intent),
            )

    def get_user_history(self, user_id: int, limit: int = 200) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT id, question, answer, confidence, intent,
                          datetime(timestamp, 'unixepoch', 'localtime') AS timestamp
                   FROM queries WHERE user_id = ?
                   ORDER BY timestamp DESC LIMIT ?""",
                (user_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_session_history(self, session_id: str, limit: int = 50) -> list[dict]:
        with self._conn() as conn:
            rows = conn.execute(
                """SELECT question, answer, confidence, intent,
                          datetime(timestamp, 'unixepoch', 'localtime') AS timestamp
                   FROM queries WHERE session_id = ?
                   ORDER BY timestamp DESC LIMIT ?""",
                (session_id, limit),
            ).fetchall()
            return [dict(r) for r in rows]

    def delete_query(self, query_id: int, user_id: int):
        with self._conn() as conn:
            conn.execute(
                "DELETE FROM queries WHERE id=? AND user_id=?", (query_id, user_id)
            )

    # ── URL cache ─────────────────────────────────────────────────────────────
    def get_cached_page(self, url: str) -> str | None:
        key = _url_hash(url)
        now = time.time()
        with self._conn() as conn:
            row = conn.execute(
                "SELECT text, cached_at FROM url_cache WHERE url_hash=?", (key,)
            ).fetchone()
            if row and (now - row["cached_at"]) < CACHE_TTL_SECONDS:
                return row["text"]
            if row:
                conn.execute("DELETE FROM url_cache WHERE url_hash=?", (key,))
        return None

    def cache_page(self, url: str, text: str):
        key = _url_hash(url)
        with self._conn() as conn:
            conn.execute(
                """INSERT OR REPLACE INTO url_cache (url_hash, url, text, cached_at)
                   VALUES (?,?,?,?)""",
                (key, url, text, time.time()),
            )

    def clear_expired_cache(self):
        cutoff = time.time() - CACHE_TTL_SECONDS
        with self._conn() as conn:
            conn.execute("DELETE FROM url_cache WHERE cached_at < ?", (cutoff,))

    # ── Comparisons ───────────────────────────────────────────────────────────
    def save_comparison(self, user_id, urls_json, question, results_json):
        with self._conn() as conn:
            conn.execute(
                """INSERT INTO comparisons (user_id, urls_json, question, results_json)
                   VALUES (?,?,?,?)""",
                (user_id, urls_json, question, results_json),
            )
