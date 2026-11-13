"""Fetch job: ``python -m app.refresh [--limit N] [--tickers KO,PG] [--fixtures]``."""

from __future__ import annotations

import argparse
import json
import logging
import random
import sqlite3
import sys
import time
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from concurrent.futures import TimeoutError as FuturesTimeout
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from tqdm import tqdm

from . import config
from .compute import recompute_all
from .db import connect, now_iso, set_meta, write_lock
from .providers import DataProvider, ProviderError, RateLimitError, get_provider
from .universe import download_universe

log = logging.getLogger("refresh")


def fetch_with_retry(provider: DataProvider, ticker: str, full: bool, attempts: int = 4) -> dict:
    last: Exception | None = None
    for i in range(attempts):
        try:
            return dict(provider.fetch(ticker, full=full))
        except RateLimitError as exc:
            last = exc
            time.sleep(min(90, 10 * (2**i)) + random.random() * 3)
        except ProviderError as exc:
            # "no data" style errors are permanent; don't retry them
            msg = str(exc).lower()
            if any(s in msg for s in ("no price history", "delisted", "no fixture", "not found", "404")):
                raise
            last = exc
            time.sleep(1.5 * (2**i) + random.random())
        except Exception as exc:  # noqa: BLE001 - network stack raises many types
            last = ProviderError(f"{type(exc).__name__}: {exc}")
            time.sleep(1.5 * (2**i) + random.random())
    assert last is not None
    raise last


# Fields that may be carried over from the last good fetch when a new fetch
# comes back without them (e.g. Yahoo served the price but not the statements).
CARRY_FIELDS = ("price", "market_cap", "eps_ttm", "ocf_ttm", "capex_ttm", "ocf_fy", "capex_fy",
                "eps_history", "fcf_history", "dividends", "price_history")
DESCRIPTIVE_FIELDS = ("name", "sector", "industry")  # copied silently, never "stale"
FUNDAMENTAL_FIELDS = {"market_cap", "eps_ttm", "ocf_ttm", "capex_ttm", "ocf_fy", "capex_fy", "eps_history", "fcf_history"}


def _empty(v: object) -> bool:
    return v is None or v == [] or v == {}


def merge_payload(new: dict, old: dict | None, old_at: str | None) -> dict:
    """Fill fields missing from ``new`` with the last good values from ``old``.

    Records each carried-over field in ``stale_since`` with the date of the
    fetch it really came from, so the UI can show it as older data.
    """
    if not old:
        return new
    out = dict(new)
    prev_since: dict[str, str] = old.get("stale_since") or {}
    since: dict[str, str] = {}
    for f in DESCRIPTIVE_FIELDS:
        if _empty(out.get(f)) and not _empty(old.get(f)):
            out[f] = old[f]
    skipped = bool(new.get("fundamentals_skipped"))
    for f in CARRY_FIELDS:
        if skipped and f in FUNDAMENTAL_FIELDS:
            continue  # intentionally not fetched for non-payers
        if _empty(new.get(f)) and not _empty(old.get(f)):
            out[f] = old[f]
            if f == "dividends":
                out["dividends_adjusted"] = old.get("dividends_adjusted", True)
                out["splits"] = old.get("splits", [])
            since[f] = prev_since.get(f) or old_at or ""
    if since:
        out["stale_since"] = since
    else:
        out.pop("stale_since", None)
    return out


def _store(conn: sqlite3.Connection, ticker: str, provider: str, payload: dict | None, error: str | None) -> None:
    now = now_iso()
    with write_lock():
        if payload is not None:
            prev = conn.execute("SELECT payload, payload_at FROM raw_data WHERE ticker = ?", (ticker,)).fetchone()
            if prev and prev["payload"]:
                payload = merge_payload(payload, json.loads(prev["payload"]), prev["payload_at"])
            conn.execute(
                """INSERT OR REPLACE INTO raw_data(ticker, provider, payload, fetched_at, payload_at, error)
                   VALUES (?,?,?,?,?,NULL)""",
                (ticker, provider, json.dumps(payload), now, now),
            )
        else:
            # keep any previous good payload (and its date); just record the error
            conn.execute(
                """INSERT INTO raw_data(ticker, provider, payload, fetched_at, payload_at, error) VALUES (?,?,NULL,?,NULL,?)
                   ON CONFLICT(ticker) DO UPDATE SET error=excluded.error, fetched_at=excluded.fetched_at""",
                (ticker, provider, now, error),
            )
        conn.commit()


def stale_tickers(conn: sqlite3.Connection, tickers: list[str], max_age: timedelta) -> list[str]:
    """Tickers needing a fetch, oldest data first (never-fetched first of all).

    Oldest-first means that if a run is cut short by its time budget, the
    next run starts with the tickers this one didn't reach.
    """
    cutoff = (datetime.now(timezone.utc) - max_age).isoformat(timespec="seconds")
    # payloads cached before price history existed count as stale so they get refetched once
    age = {
        r["ticker"]: (r["payload_at"] or "", r["error"] is None and bool(r["has_prices"]))
        for r in conn.execute(
            """SELECT ticker, payload_at, error, instr(COALESCE(payload, ''), '"price_history"') AS has_prices
               FROM raw_data"""
        )
    }
    todo = [t for t in tickers if not (t in age and age[t][1] and age[t][0] >= cutoff)]
    order = {t: i for i, t in enumerate(tickers)}
    return sorted(todo, key=lambda t: (age.get(t, ("", False))[0], order[t]))


def fetch_all(
    conn: sqlite3.Connection,
    provider: DataProvider,
    todo: list[str],
    workers: int,
    full: bool = False,
    budget_seconds: float | None = None,
    progress: bool = True,
) -> dict[str, int]:
    """Fetch ``todo`` concurrently, storing each result as it arrives.

    With ``budget_seconds`` set, stops starting new tickers once the budget is
    spent; tickers already in flight are finished and stored. Unfetched
    tickers keep their previous data.
    """
    errors = 0
    stored: set[str] = set()
    deadline = time.monotonic() + budget_seconds if budget_seconds else None

    def handle(fut: Future[dict], t: str) -> None:
        nonlocal errors
        stored.add(t)
        try:
            _store(conn, t, provider.name, fut.result(), None)
        except Exception as exc:  # noqa: BLE001 - log and skip
            errors += 1
            log.warning("%s failed: %s", t, exc)
            _store(conn, t, provider.name, None, str(exc)[:500])

    pool = ThreadPoolExecutor(max_workers=max(1, workers))
    futs = {pool.submit(fetch_with_retry, provider, t, full): t for t in todo}
    bar = tqdm(total=len(futs), unit="tkr", desc="Fetching", dynamic_ncols=True, disable=not progress)
    timed_out = False
    try:
        remaining = None if deadline is None else max(0.0, deadline - time.monotonic())
        for fut in as_completed(futs, timeout=remaining):
            handle(fut, futs[fut])
            bar.update(1)
            bar.set_postfix(errors=errors)
    except FuturesTimeout:
        timed_out = True
        log.warning("time budget reached; cancelling %d queued tickers", sum(1 for f in futs if not f.done()))
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
        bar.close()
    if timed_out:  # store whatever finished while shutting down
        for fut, t in futs.items():
            if t not in stored and fut.done() and not fut.cancelled():
                handle(fut, t)
    return {"fetched": len(stored), "errors": errors, "not_reached": len(todo) - len(stored)}


def fixtures_as_of() -> date:
    manifest = json.loads((config.FIXTURES_DIR / "manifest.json").read_text())
    return date.fromisoformat(manifest["as_of"])


def build_fixture_db(path: Path | None = None) -> sqlite3.Connection:
    """(Re)build the offline fixture database. Used by tests and --fixtures."""
    from .providers.fixture_provider import FixtureProvider

    conn = connect(path or config.db_path(fixtures=True))
    prov = FixtureProvider()
    set_meta(conn, "last_run_started", now_iso())
    with write_lock():
        conn.execute("DELETE FROM universe")
        conn.execute("DELETE FROM raw_data")
        conn.executemany(
            "INSERT INTO universe(ticker, name, exchange, added_at) VALUES (?,?,?,?)",
            [(t, n, "FIXTURE", now_iso()) for t, n in prov.tickers()],
        )
        conn.commit()
    for t, _ in prov.tickers():
        try:
            _store(conn, t, prov.name, dict(prov.fetch(t)), None)
        except ProviderError as exc:
            _store(conn, t, prov.name, None, str(exc))
    as_of = fixtures_as_of()
    recompute_all(conn, as_of)
    set_meta(conn, "last_refresh", now_iso())
    set_meta(conn, "as_of", as_of.isoformat())
    set_meta(conn, "provider", prov.name)
    set_meta(conn, "universe_size", str(len(prov.tickers())))
    return conn


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Refresh dividend screener data")
    ap.add_argument("--fixtures", action="store_true", help="build the offline fixture DB and exit")
    ap.add_argument("--limit", type=int, help="only process the first N universe tickers")
    ap.add_argument("--tickers", help="comma-separated list, e.g. AAPL,KO,PG")
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--max-age-hours", type=float, default=24.0, help="skip tickers fetched more recently")
    ap.add_argument("--force", action="store_true", help="refetch even if cached within max-age")
    ap.add_argument("--full", action="store_true", help="fetch fundamentals even for non-payers (slower)")
    ap.add_argument("--retry-errors", action="store_true", help="only refetch tickers whose last fetch failed")
    ap.add_argument("--compute-only", action="store_true", help="recompute metrics from cache, no network")
    ap.add_argument("--provider", default=config.PROVIDER)
    ap.add_argument(
        "--time-budget-min", type=float, default=None,
        help="stop starting new fetches after N minutes, then compute with fresh + previous data",
    )
    args = ap.parse_args(argv)

    data_dir = config.DATA_DIR
    data_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[logging.FileHandler(data_dir / "refresh.log")],
    )

    if args.fixtures:
        conn = build_fixture_db()
        n = conn.execute("SELECT COUNT(*) FROM metrics").fetchone()[0]
        print(f"Fixture DB built at {config.db_path(True)} with {n} tickers.")
        return 0

    conn = connect(config.db_path(fixtures=False))

    if args.compute_only:
        n = recompute_all(conn, date.today())
        print(f"Recomputed metrics for {n} tickers.")
        return 0

    # ---- universe ---------------------------------------------------------
    if args.tickers:
        tickers = [t.strip().upper().replace(".", "-") for t in args.tickers.split(",") if t.strip()]
        known = {r["ticker"] for r in conn.execute("SELECT ticker FROM universe")}
        with write_lock():
            conn.executemany(
                "INSERT OR IGNORE INTO universe(ticker, name, exchange, added_at) VALUES (?,?,?,?)",
                [(t, None, None, now_iso()) for t in tickers if t not in known],
            )
            conn.commit()
    else:
        print("Downloading US symbol lists from nasdaqtrader.com ...")
        try:
            uni = download_universe(data_dir)
        except Exception as exc:  # noqa: BLE001
            uni = [(r["ticker"], r["name"], r["exchange"]) for r in conn.execute("SELECT * FROM universe ORDER BY ticker")]
            if not uni:
                print(f"Could not download universe: {exc}", file=sys.stderr)
                return 1
            print(f"Could not download universe ({exc}); reusing the {len(uni):,} tickers from the last run.", file=sys.stderr)
        with write_lock():
            conn.executemany(
                """INSERT INTO universe(ticker, name, exchange, added_at) VALUES (?,?,?,?)
                   ON CONFLICT(ticker) DO UPDATE SET name=excluded.name, exchange=excluded.exchange""",
                [(s, n, e, now_iso()) for s, n, e in uni],
            )
            conn.commit()
        set_meta(conn, "universe_size", str(len(uni)))
        print(f"Universe: {len(uni):,} common stocks after exclusions.")
        tickers = [s for s, _, _ in uni]
        if args.limit:
            tickers = tickers[: args.limit]

    if args.retry_errors:
        errs = {r["ticker"] for r in conn.execute("SELECT ticker FROM raw_data WHERE error IS NOT NULL")}
        tickers = [t for t in tickers if t in errs]
    todo = tickers if args.force else stale_tickers(conn, tickers, timedelta(hours=args.max_age_hours))
    skipped = len(tickers) - len(todo)
    if skipped:
        print(f"Skipping {skipped:,} tickers refreshed within the last {args.max_age_hours:g}h.")

    provider = get_provider(args.provider)
    start = time.time()
    # Only a full-universe run starts a new "run" for staleness purposes; a
    # --tickers/--limit dev run or a --retry-errors pass must not flag
    # everything it didn't touch as "not refreshed".
    if not (args.retry_errors or args.tickers or args.limit):
        set_meta(conn, "last_run_started", now_iso())
    budget = args.time_budget_min * 60 if args.time_budget_min else None
    stats = fetch_all(conn, provider, todo, args.workers, args.full, budget)
    set_meta(conn, "last_run_not_reached", str(stats["not_reached"]))
    if stats["not_reached"]:
        print(f"Time budget reached: {stats['not_reached']:,} tickers not refreshed this run (they keep previous data).")

    n = recompute_all(conn, date.today())
    set_meta(conn, "last_refresh", now_iso())
    set_meta(conn, "as_of", date.today().isoformat())
    set_meta(conn, "provider", provider.name)
    if not conn.execute("SELECT 1 FROM meta WHERE key='universe_size'").fetchone():
        set_meta(conn, "universe_size", str(conn.execute("SELECT COUNT(*) FROM universe").fetchone()[0]))
    print(
        f"Fetched {stats['fetched']:,} tickers in {time.time() - start:,.0f}s with {stats['errors']:,} errors "
        f"(see {data_dir / 'refresh.log'}). Metrics computed for {n:,} tickers."
    )
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")  # single-file DB for caching/copying
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
