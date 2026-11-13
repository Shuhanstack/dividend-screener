"""Fetch job: ``python -m app.refresh [--limit N] [--tickers KO,PG] [--fixtures]``."""

from __future__ import annotations

import argparse
import json
import logging
import random
import sqlite3
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
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


def _store(conn: sqlite3.Connection, ticker: str, provider: str, payload: dict | None, error: str | None) -> None:
    with write_lock():
        if payload is not None:
            conn.execute(
                "INSERT OR REPLACE INTO raw_data(ticker, provider, payload, fetched_at, error) VALUES (?,?,?,?,NULL)",
                (ticker, provider, json.dumps(payload), now_iso()),
            )
        else:
            # keep any previous good payload; just record the error
            conn.execute(
                """INSERT INTO raw_data(ticker, provider, payload, fetched_at, error) VALUES (?,?,NULL,?,?)
                   ON CONFLICT(ticker) DO UPDATE SET error=excluded.error, fetched_at=excluded.fetched_at""",
                (ticker, provider, now_iso(), error),
            )
        conn.commit()


def stale_tickers(conn: sqlite3.Connection, tickers: list[str], max_age: timedelta) -> list[str]:
    cutoff = (datetime.now(timezone.utc) - max_age).isoformat(timespec="seconds")
    fresh = {
        r["ticker"]
        for r in conn.execute(
            "SELECT ticker FROM raw_data WHERE payload IS NOT NULL AND error IS NULL AND fetched_at >= ?", (cutoff,)
        )
    }
    return [t for t in tickers if t not in fresh]


def fixtures_as_of() -> date:
    manifest = json.loads((config.FIXTURES_DIR / "manifest.json").read_text())
    return date.fromisoformat(manifest["as_of"])


def build_fixture_db(path: Path | None = None) -> sqlite3.Connection:
    """(Re)build the offline fixture database. Used by tests and --fixtures."""
    from .providers.fixture_provider import FixtureProvider

    conn = connect(path or config.db_path(fixtures=True))
    prov = FixtureProvider()
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
            print(f"Could not download universe: {exc}", file=sys.stderr)
            return 1
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
    errors = 0
    start = time.time()
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as pool:
        futs = {pool.submit(fetch_with_retry, provider, t, args.full): t for t in todo}
        bar = tqdm(total=len(futs), unit="tkr", desc="Fetching", dynamic_ncols=True)
        for fut in as_completed(futs):
            t = futs[fut]
            try:
                _store(conn, t, provider.name, fut.result(), None)
            except Exception as exc:  # noqa: BLE001 - log and skip
                errors += 1
                log.warning("%s failed: %s", t, exc)
                _store(conn, t, provider.name, None, str(exc)[:500])
            bar.update(1)
            bar.set_postfix(errors=errors)
        bar.close()

    n = recompute_all(conn, date.today())
    set_meta(conn, "last_refresh", now_iso())
    set_meta(conn, "as_of", date.today().isoformat())
    set_meta(conn, "provider", provider.name)
    if not conn.execute("SELECT 1 FROM meta WHERE key='universe_size'").fetchone():
        set_meta(conn, "universe_size", str(conn.execute("SELECT COUNT(*) FROM universe").fetchone()[0]))
    print(
        f"Fetched {len(todo):,} tickers in {time.time() - start:,.0f}s with {errors:,} errors "
        f"(see {data_dir / 'refresh.log'}). Metrics computed for {n:,} tickers."
    )
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")  # single-file DB for caching/copying
    conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
