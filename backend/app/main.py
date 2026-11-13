"""FastAPI app. Run with ``uvicorn app.main:app`` (set DIVSCREEN_FIXTURES=1 for offline mode)."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import config
from .db import connect, get_meta, now_iso, write_lock
from .screen import Thresholds, active_rules, checks, eliminated_at, first_failure, load_rows, public_row, run_screen


class State:
    conn: sqlite3.Connection
    rows: list[dict[str, Any]] = []
    rows_key: str | None = None
    lock = threading.Lock()


state = State()


def _open() -> None:
    fixtures = config.fixtures_mode()
    path = config.db_path(fixtures)
    if fixtures:
        from .refresh import build_fixture_db

        state.conn = build_fixture_db(path)
    else:
        state.conn = connect(path)
        # metrics is derived data; a schema migration rebuilds it empty, so recompute from the cache
        has_metrics = state.conn.execute("SELECT 1 FROM metrics LIMIT 1").fetchone()
        has_raw = state.conn.execute("SELECT 1 FROM raw_data WHERE payload IS NOT NULL LIMIT 1").fetchone()
        if has_raw and not has_metrics:
            from datetime import date

            from .compute import recompute_all

            as_of = get_meta(state.conn, "as_of")
            recompute_all(state.conn, date.fromisoformat(as_of) if as_of else date.today())


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    _open()
    yield
    state.conn.close()


app = FastAPI(title="Dividend Pocket-Money Screener", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])


def rows() -> list[dict[str, Any]]:
    """Metrics rows, cached in memory until the next refresh."""
    key = get_meta(state.conn, "last_refresh")
    with state.lock:
        if key != state.rows_key or not state.rows:
            state.rows = load_rows(state.conn)
            state.rows_key = key
        return state.rows


def thresholds(
    yield_min: float = Query(3.0),
    payout_max: float = Query(70.0),
    fcf_min: float = Query(0.0),
    paid_years_min: int = Query(5, ge=0),
    growth_years_min: int = Query(5, ge=0),
    ignore_specials: bool = Query(True),
    price_filter: bool = Query(False),
    price_drop_max: float = Query(20.0, ge=0),
) -> Thresholds:
    return Thresholds(
        yield_min, payout_max, fcf_min, paid_years_min, growth_years_min, ignore_specials, price_filter, price_drop_max
    )


def watch_set() -> set[str]:
    return {r["ticker"] for r in state.conn.execute("SELECT ticker FROM watchlist")}


@app.get("/api/screen")
def screen(th: Thresholds = Depends(thresholds)) -> dict[str, Any]:
    out = run_screen(rows(), th)
    w = watch_set()
    for r in out["results"]:
        r["watched"] = r["ticker"] in w
    return out


@app.get("/api/screen/eliminated")
def eliminated(step: int = Query(..., ge=1, le=6), limit: int = Query(500, le=10000), th: Thresholds = Depends(thresholds)) -> dict[str, Any]:
    items = eliminated_at(rows(), th, step)
    return {
        "step": step,
        "total": len(items),
        "missing_data": sum(1 for i in items if i["missing_data"]),
        "items": items[:limit],
    }


@app.get("/api/stock/{ticker}")
def stock(ticker: str, th: Thresholds = Depends(thresholds)) -> dict[str, Any]:
    t = ticker.upper()
    r = state.conn.execute("SELECT * FROM metrics WHERE ticker = ?", (t,)).fetchone()
    if not r:
        raise HTTPException(404, f"{t} not found")
    row = dict(r)
    detail = json.loads(row.pop("detail") or "{}")
    raw = state.conn.execute("SELECT fetched_at, error FROM raw_data WHERE ticker = ?", (t,)).fetchone()
    annual = detail.get("annual_reg" if th.ignore_specials else "annual_all", {})
    return {
        **public_row(row, th),
        "checks": checks(row, th),
        "annual_dividends": [{"year": int(y), "total": v} for y, v in sorted(annual.items())],
        "annual_dividends_all": [{"year": int(y), "total": v} for y, v in sorted(detail.get("annual_all", {}).items())],
        "specials": detail.get("specials", []),
        "recent_payments": detail.get("recent_payments", []),
        "splits": detail.get("splits", []),
        "eps_history": detail.get("eps_history", {}),
        "fcf_history": detail.get("fcf_history", {}),
        "last_completed_year": detail.get("last_completed_year"),
        "fundamentals_skipped": detail.get("fundamentals_skipped", False),
        "stale_since": detail.get("stale_since", {}),
        "fetched_at": raw["fetched_at"] if raw else None,
        "fetch_error": raw["error"] if raw else None,
        "watched": t in watch_set(),
        "yahoo_url": f"https://finance.yahoo.com/quote/{t}",
    }


@app.get("/api/stock/{ticker}/prices")
def prices(ticker: str) -> dict[str, Any]:
    """Weekly closes for the last ~3 years.

    Served from the cached payload. Payloads cached before price history was
    added are backfilled once from Yahoo on first request (real-data mode only).
    """
    t = ticker.upper()
    row = state.conn.execute("SELECT payload FROM raw_data WHERE ticker = ?", (t,)).fetchone()
    if not row:
        raise HTTPException(404, f"{t} not found")
    payload = json.loads(row["payload"]) if row["payload"] else None
    points = (payload or {}).get("price_history") or []
    source, error = "cache", None
    if not points and payload is not None and not config.fixtures_mode() and config.PROVIDER == "yfinance":
        from .providers.yfinance_provider import fetch_price_history

        try:
            points = fetch_price_history(t)
            source = "live"
            if points:
                payload["price_history"] = points
                with write_lock():  # cache it; payload_at is unchanged (other fields not refreshed)
                    state.conn.execute("UPDATE raw_data SET payload = ? WHERE ticker = ?", (json.dumps(payload), t))
                    state.conn.commit()
        except Exception as exc:  # noqa: BLE001 - network/provider errors
            error = str(exc)[:200]
    return {"ticker": t, "points": [{"date": d, "close": c} for d, c in points], "source": source, "error": error}


@app.get("/api/meta")
def meta() -> dict[str, Any]:
    c = state.conn
    errs = [dict(r) for r in c.execute("SELECT ticker, error, fetched_at FROM raw_data WHERE error IS NOT NULL ORDER BY ticker")]
    return {
        "last_refresh": get_meta(c, "last_refresh"),
        "as_of": get_meta(c, "as_of"),
        "provider": get_meta(c, "provider"),
        "fixtures_mode": config.fixtures_mode(),
        "universe_size": int(get_meta(c, "universe_size") or 0),
        "screened": c.execute("SELECT COUNT(*) FROM metrics").fetchone()[0],
        "fetch_errors": len(errs),
        "stale_count": c.execute("SELECT COUNT(*) FROM metrics WHERE stale IS NOT NULL").fetchone()[0],
        "not_refreshed_count": c.execute("SELECT COUNT(*) FROM metrics WHERE stale = '[\"all\"]'").fetchone()[0],
        "error_tickers": errs[:500],
    }


@app.get("/api/watchlist")
def get_watchlist(th: Thresholds = Depends(thresholds)) -> dict[str, Any]:
    w = {r["ticker"]: r["added_at"] for r in state.conn.execute("SELECT ticker, added_at FROM watchlist")}
    by_ticker = {r["ticker"]: r for r in rows() if r["ticker"] in w}
    items = []
    for t, added in sorted(w.items()):
        r = by_ticker.get(t)
        if r is None:
            items.append({"ticker": t, "added_at": added, "has_data": False, "fails": [], "missing": [], "watched": True})
            continue
        res = [(s, fn(r, th)) for s, _, fn in active_rules(th)]
        pr = public_row(r, th)
        pr.update(
            added_at=added,
            watched=True,
            fails=[s for s, o in res if o == "fail"],
            missing=[s for s, o in res if o == "missing"],
            first_failure=(first_failure(r, th) or (None,))[0],
        )
        items.append(pr)
    return {"items": items}


@app.post("/api/watchlist/{ticker}")
def add_watch(ticker: str) -> dict[str, Any]:
    with write_lock():
        state.conn.execute("INSERT OR IGNORE INTO watchlist(ticker, added_at) VALUES (?, ?)", (ticker.upper(), now_iso()))
        state.conn.commit()
    return {"ok": True, "ticker": ticker.upper()}


@app.delete("/api/watchlist/{ticker}")
def del_watch(ticker: str) -> dict[str, Any]:
    with write_lock():
        state.conn.execute("DELETE FROM watchlist WHERE ticker = ?", (ticker.upper(),))
        state.conn.commit()
    return {"ok": True, "ticker": ticker.upper()}


# Serve the built frontend (``make build``) if present.
_dist = config.ROOT_DIR / "frontend" / "dist"
if _dist.exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str) -> FileResponse:
        f = _dist / path
        return FileResponse(f if path and f.is_file() else _dist / "index.html")
