"""SQLite storage (plain sqlite3)."""

from __future__ import annotations

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS universe (
    ticker      TEXT PRIMARY KEY,
    name        TEXT,
    exchange    TEXT,
    added_at    TEXT
);
CREATE TABLE IF NOT EXISTS raw_data (
    ticker      TEXT PRIMARY KEY,
    provider    TEXT,
    payload     TEXT,          -- normalized JSON (see providers.base.TickerData)
    fetched_at  TEXT,          -- last fetch *attempt*
    payload_at  TEXT,          -- when `payload` was last fetched successfully
    error       TEXT           -- last error, NULL when the latest attempt succeeded
);
CREATE TABLE IF NOT EXISTS metrics (
    ticker              TEXT PRIMARY KEY,
    name                TEXT,
    sector              TEXT,
    industry            TEXT,
    market_cap          REAL,
    price               REAL,
    eps_ttm             REAL,
    fcf                 REAL,
    fcf_source          TEXT,
    has_data            INTEGER,     -- 0 when the fetch failed entirely
    has_special         INTEGER,
    -- variants: _all = every payment, _reg = specials ignored
    dps_ttm_all         REAL,
    dps_ttm_reg         REAL,
    yield_all           REAL,
    yield_reg           REAL,
    payout_all          REAL,
    payout_reg          REAL,
    paid_years_all      INTEGER,
    paid_years_reg      INTEGER,
    growth_years_all    INTEGER,
    growth_years_reg    INTEGER,
    price_change_3y     REAL,        -- % price change over the last 3 years (NULL if < 3y history)
    detail              TEXT,        -- JSON: annual dividends, specials, histories
    data_as_of          TEXT,        -- when this ticker's data was last fetched successfully
    stale               TEXT,        -- JSON list: ["all"] = not refreshed in the latest run,
                                     -- or field names carried over from an older fetch
    computed_at         TEXT
);
CREATE TABLE IF NOT EXISTS watchlist (
    ticker      TEXT PRIMARY KEY,
    added_at    TEXT
);
CREATE TABLE IF NOT EXISTS meta (
    key         TEXT PRIMARY KEY,
    value       TEXT
);
"""

_lock = threading.Lock()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path: Path) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, check_same_thread=False, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    """Add columns introduced after a database was first created."""
    raw_cols = {r[1] for r in conn.execute("PRAGMA table_info(raw_data)")}
    if "payload_at" not in raw_cols:
        conn.execute("ALTER TABLE raw_data ADD COLUMN payload_at TEXT")
        conn.execute("UPDATE raw_data SET payload_at = fetched_at WHERE payload IS NOT NULL")
    m_cols = {r[1] for r in conn.execute("PRAGMA table_info(metrics)")}
    if not {"stale", "price_change_3y"} <= m_cols:  # metrics is derived data: just rebuild the table
        conn.execute("DROP TABLE metrics")
        conn.executescript(SCHEMA)
    conn.commit()


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    with _lock:
        conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES (?, ?)", (key, value))
        conn.commit()


def get_meta(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def write_lock() -> threading.Lock:
    return _lock
