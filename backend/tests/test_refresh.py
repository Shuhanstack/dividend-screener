"""Failure handling: field carry-over, error fallback, time budget, staleness."""
from __future__ import annotations

import json
import time
from datetime import date
from pathlib import Path

from app.compute import recompute_all
from app.db import connect, set_meta
from app.providers.base import DataProvider, ProviderError, TickerData
from app.refresh import _store, fetch_all, merge_payload, stale_tickers
from app.screen import load_rows, public_row, Thresholds

GOOD: dict = {
    "ticker": "KO", "name": "Coke", "sector": "Staples", "price": 60.0, "market_cap": 1e11,
    "eps_ttm": 3.0, "ocf_ttm": 10.0, "capex_ttm": -2.0,
    "dividends": [[f"{y}-0{q}-15", 0.5 + 0.01 * y - 20] for y in range(2015, 2026) for q in (3, 6, 9)],
    "dividends_adjusted": True, "splits": [], "eps_history": {"2024": 2.9}, "fcf_history": {"2024": 8.0},
}


def test_merge_fills_missing_fields_and_keeps_original_date() -> None:
    new = {**GOOD, "eps_ttm": None, "ocf_ttm": None, "eps_history": {}}
    m1 = merge_payload(new, GOOD, "2026-11-01T00:00:00+00:00")
    assert m1["eps_ttm"] == 3.0 and m1["ocf_ttm"] == 10.0 and m1["eps_history"] == {"2024": 2.9}
    assert m1["stale_since"] == dict.fromkeys(["eps_ttm", "ocf_ttm", "eps_history"], "2026-11-01T00:00:00+00:00")
    # a week later still missing: the date stays the date of the real value
    m2 = merge_payload(new, m1, "2026-11-08T00:00:00+00:00")
    assert m2["stale_since"]["eps_ttm"] == "2026-11-01T00:00:00+00:00"
    # value comes back: no longer stale
    assert "stale_since" not in merge_payload(dict(GOOD), m2, "2026-11-15T00:00:00+00:00")


def test_merge_keeps_dividend_history_when_yahoo_returns_none() -> None:
    m = merge_payload({**GOOD, "dividends": []}, GOOD, "t0")
    assert m["dividends"] == GOOD["dividends"] and "dividends" in m["stale_since"]


def test_merge_skips_fundamentals_for_non_payers() -> None:
    new = {"ticker": "KO", "price": 61.0, "dividends": GOOD["dividends"], "fundamentals_skipped": True}
    m = merge_payload(new, GOOD, "t0")
    assert m.get("eps_ttm") is None and "stale_since" not in m
    assert m["name"] == "Coke"  # descriptive fields are copied silently


def test_store_error_keeps_previous_payload(tmp_path: Path) -> None:
    conn = connect(tmp_path / "t.db")
    _store(conn, "KO", "test", dict(GOOD), None)
    before = conn.execute("SELECT payload, payload_at FROM raw_data").fetchone()
    _store(conn, "KO", "test", None, "RateLimit")
    after = conn.execute("SELECT payload, payload_at, error FROM raw_data").fetchone()
    assert after["payload"] == before["payload"] and after["payload_at"] == before["payload_at"]
    assert after["error"] == "RateLimit"


def test_stale_tickers_oldest_first(tmp_path: Path) -> None:
    conn = connect(tmp_path / "t.db")
    for t, at in [("A", "2026-01-03"), ("B", "2026-01-01"), ("C", "2026-01-02")]:
        conn.execute("INSERT INTO raw_data(ticker, payload, fetched_at, payload_at) VALUES (?, '{}', ?, ?)", (t, at, at))
    assert stale_tickers(conn, ["A", "B", "C", "NEW"], __import__("datetime").timedelta(hours=24)) == ["NEW", "B", "C", "A"]


class SlowProvider(DataProvider):
    name = "slow"

    def __init__(self, fail: set[str] | None = None) -> None:
        self.fail = fail or set()

    def fetch(self, ticker: str, full: bool = False) -> TickerData:
        time.sleep(0.15)
        if ticker in self.fail:
            raise ProviderError("no price history (simulated)")
        return {**GOOD, "ticker": ticker, "price": 70.0}  # type: ignore[typeddict-item]


def test_time_budget_publishes_fresh_plus_previous(tmp_path: Path) -> None:
    conn = connect(tmp_path / "t.db")
    tickers = [f"T{i}" for i in range(10)]
    # last week: everything fetched with price 60
    set_meta(conn, "last_run_started", "2026-11-01T00:00:00+00:00")
    for t in tickers:
        _store(conn, t, "test", {**GOOD, "ticker": t}, None)
    conn.execute("UPDATE raw_data SET payload_at='2026-11-01T00:00:01+00:00', fetched_at='2026-11-01T00:00:01+00:00'")
    # this week: slow provider, budget allows only a few; T0 fails outright
    set_meta(conn, "last_run_started", "2026-11-08T00:00:00+00:00")
    todo = stale_tickers(conn, tickers, __import__("datetime").timedelta(hours=24))
    stats = fetch_all(conn, SlowProvider(fail={"T0"}), todo, workers=1, budget_seconds=0.5, progress=False)
    assert 0 < stats["fetched"] < 10 and stats["not_reached"] == 10 - stats["fetched"]

    recompute_all(conn, date(2026, 11, 8))
    rows = {r["ticker"]: public_row(r, Thresholds()) for r in load_rows(conn)}
    assert len(rows) == 10 and all(r["has_data"] for r in rows.values())  # nothing lost
    fresh = [t for t, r in rows.items() if r["price"] == 70.0]
    old = [t for t, r in rows.items() if r["price"] == 60.0]
    assert fresh and old and len(fresh) + len(old) == 10
    assert all(rows[t]["stale"] == [] for t in fresh)
    assert all(rows[t]["stale"] == ["all"] for t in old)
    assert "T0" in old  # failed fetch -> previous data, flagged


def test_field_level_stale_reaches_metrics(tmp_path: Path) -> None:
    conn = connect(tmp_path / "t.db")
    set_meta(conn, "last_run_started", "2000-01-01T00:00:00+00:00")
    _store(conn, "KO", "test", dict(GOOD), None)
    _store(conn, "KO", "test", {**GOOD, "eps_ttm": None}, None)
    recompute_all(conn, date(2026, 11, 8))
    r = load_rows(conn)[0]
    assert r["eps_ttm"] == 3.0 and json.loads(r["stale"]) == ["eps_ttm"]
