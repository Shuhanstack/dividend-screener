"""Turn cached raw payloads into rows of the ``metrics`` table."""

from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any

from . import metrics as m
from .db import now_iso, write_lock
from .providers.base import TickerData

HISTORY_YEARS = 20
FRESH_WINDOW = timedelta(hours=24)  # matches refresh's default --max-age-hours


def compute_row(
    ticker: str,
    payload: TickerData | None,
    as_of: date,
    fallback_name: str | None = None,
    payload_at: str | None = None,
    latest_error: str | None = None,
    run_started: str | None = None,
) -> dict[str, Any]:
    row: dict[str, Any] = {"ticker": ticker, "name": fallback_name, "has_data": 0, "computed_at": now_iso()}
    if payload is None:
        return row

    # Staleness: whole record from an older fetch, or individual fields carried over.
    stale_since: dict[str, str] = dict(payload.get("stale_since") or {})  # type: ignore[call-overload]
    # Data fetched up to 24h before the run started was skipped as fresh, not missed.
    cutoff = (datetime.fromisoformat(run_started) - FRESH_WINDOW).isoformat(timespec="seconds") if run_started else None
    not_refreshed = bool(latest_error) or bool(cutoff and payload_at and payload_at < cutoff)
    stale = ["all"] if not_refreshed else sorted(stale_since)
    row["data_as_of"] = payload_at
    row["stale"] = json.dumps(stale) if stale else None

    payments: list[m.Payment] = [(date.fromisoformat(str(d)[:10]), float(a)) for d, a in payload.get("dividends", [])]
    payments.sort()
    splits = [(date.fromisoformat(str(d)[:10]), float(r)) for d, r in payload.get("splits", [])]
    if not payload.get("dividends_adjusted", True):
        payments = m.split_adjust(payments, splits)

    flags = m.special_flags(payments)
    s_all = m.dividend_stats(payments, as_of, ignore_specials=False)
    s_reg = m.dividend_stats(payments, as_of, ignore_specials=True)

    price = payload.get("price")
    eps = payload.get("eps_ttm")
    fcf, fcf_src = m.free_cash_flow(
        payload.get("ocf_ttm"), payload.get("capex_ttm"), payload.get("ocf_fy"), payload.get("capex_fy")
    )

    ly = m.last_completed_year(as_of)
    first = ly - HISTORY_YEARS + 1
    detail = {
        "as_of": as_of.isoformat(),
        "last_completed_year": ly,
        "annual_all": {str(y): v for y, v in s_all.annual.items() if y >= first},
        "annual_reg": {str(y): v for y, v in s_reg.annual.items() if y >= first},
        "specials": [[d.isoformat(), a] for (d, a), f in zip(payments, flags) if f],
        "recent_payments": [[d.isoformat(), round(a, 6)] for d, a in payments[-12:]],
        "splits": [[d.isoformat(), r] for d, r in splits],
        "eps_history": payload.get("eps_history", {}),
        "fcf_history": payload.get("fcf_history", {}),
        "fundamentals_skipped": bool(payload.get("fundamentals_skipped")),
        "stale_since": stale_since,
        "ocf": payload.get("ocf_ttm") if fcf_src == "ttm" else payload.get("ocf_fy"),
        "capex": payload.get("capex_ttm") if fcf_src == "ttm" else payload.get("capex_fy"),
    }

    prices = [(date.fromisoformat(str(d)[:10]), float(c)) for d, c in payload.get("price_history", []) or []]

    row.update(
        price_change_3y=m.price_change(prices),
        name=payload.get("name") or fallback_name,
        sector=payload.get("sector"),
        industry=payload.get("industry"),
        market_cap=payload.get("market_cap"),
        price=price,
        eps_ttm=eps,
        fcf=fcf,
        fcf_source=fcf_src,
        has_data=1,
        has_special=int(any(flags)),
        dps_ttm_all=s_all.dps_ttm,
        dps_ttm_reg=s_reg.dps_ttm,
        yield_all=m.dividend_yield(s_all.dps_ttm, price),
        yield_reg=m.dividend_yield(s_reg.dps_ttm, price),
        payout_all=m.payout_ratio(s_all.dps_ttm, eps),
        payout_reg=m.payout_ratio(s_reg.dps_ttm, eps),
        paid_years_all=s_all.paid_years,
        paid_years_reg=s_reg.paid_years,
        growth_years_all=s_all.growth_years,
        growth_years_reg=s_reg.growth_years,
        detail=json.dumps(detail),
    )
    return row


COLUMNS = [
    "ticker", "name", "sector", "industry", "market_cap", "price", "eps_ttm", "fcf", "fcf_source",
    "has_data", "has_special", "dps_ttm_all", "dps_ttm_reg", "yield_all", "yield_reg", "payout_all",
    "payout_reg", "paid_years_all", "paid_years_reg", "growth_years_all", "growth_years_reg", "price_change_3y", "detail",
    "data_as_of", "stale", "computed_at",
]


def recompute_all(conn: sqlite3.Connection, as_of: date) -> int:
    """Rebuild the metrics table for every ticker we have attempted to fetch.

    Tickers whose fetch failed (payload NULL) still get a row so the funnel can
    count them as missing data. Universe tickers never attempted are omitted.
    """
    recs = conn.execute(
        """SELECT r.ticker, r.payload, r.payload_at, r.error, u.name
           FROM raw_data r LEFT JOIN universe u ON u.ticker = r.ticker"""
    ).fetchall()
    started = conn.execute("SELECT value FROM meta WHERE key = 'last_run_started'").fetchone()
    run_started = started[0] if started else None
    rows = [
        compute_row(
            r["ticker"], json.loads(r["payload"]) if r["payload"] else None, as_of, r["name"],
            payload_at=r["payload_at"], latest_error=r["error"], run_started=run_started,
        )
        for r in recs
    ]
    placeholders = ",".join("?" for _ in COLUMNS)
    with write_lock():
        conn.execute("DELETE FROM metrics")
        conn.executemany(
            f"INSERT INTO metrics ({','.join(COLUMNS)}) VALUES ({placeholders})",
            [tuple(r.get(c) for c in COLUMNS) for r in rows],
        )
        conn.commit()
    return len(rows)
