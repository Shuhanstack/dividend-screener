"""Screening over the precomputed metrics table (no network calls)."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any, Callable, Literal

Outcome = Literal["pass", "fail", "missing"]


@dataclass(frozen=True)
class Thresholds:
    yield_min: float = 3.0
    payout_max: float = 70.0
    fcf_min: float = 0.0
    paid_years_min: int = 5
    growth_years_min: int = 5
    ignore_specials: bool = True


def _v(row: dict[str, Any], base: str, th: Thresholds) -> Any:
    return row.get(f"{base}_{'reg' if th.ignore_specials else 'all'}")


def r_yield(row: dict[str, Any], th: Thresholds) -> Outcome:
    if not row.get("has_data"):
        return "missing"
    y = _v(row, "yield", th)
    if y is None:
        return "missing"
    return "pass" if y >= th.yield_min else "fail"


def r_payout(row: dict[str, Any], th: Thresholds) -> Outcome:
    eps = row.get("eps_ttm")
    if eps is None:
        return "missing"
    if eps <= 0:
        return "fail"  # negative/zero earnings: dividend not covered
    p = _v(row, "payout", th)
    if p is None:
        return "missing"
    return "pass" if p <= th.payout_max else "fail"


def r_fcf(row: dict[str, Any], th: Thresholds) -> Outcome:
    f = row.get("fcf")
    if f is None:
        return "missing"
    return "pass" if f > th.fcf_min else "fail"


def r_paid(row: dict[str, Any], th: Thresholds) -> Outcome:
    n = _v(row, "paid_years", th)
    if not row.get("has_data") or n is None:
        return "missing"
    return "pass" if n >= th.paid_years_min else "fail"


def r_growth(row: dict[str, Any], th: Thresholds) -> Outcome:
    n = _v(row, "growth_years", th)
    if not row.get("has_data") or n is None:
        return "missing"
    return "pass" if n >= th.growth_years_min else "fail"


RULES: list[tuple[int, str, Callable[[dict[str, Any], Thresholds], Outcome]]] = [
    (1, "Pays a dividend", r_yield),
    (2, "Can afford it", r_payout),
    (3, "Has the cash", r_fcf),
    (4, "Pays reliably", r_paid),
    (5, "Pays more each year", r_growth),
]

LIST_COLUMNS = (
    "ticker, name, sector, industry, market_cap, price, eps_ttm, fcf, fcf_source, has_data, has_special, "
    "dps_ttm_all, dps_ttm_reg, yield_all, yield_reg, payout_all, payout_reg, paid_years_all, paid_years_reg, "
    "growth_years_all, growth_years_reg"
)


def load_rows(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return [dict(r) for r in conn.execute(f"SELECT {LIST_COLUMNS} FROM metrics")]


def evaluate(row: dict[str, Any], th: Thresholds) -> list[Outcome]:
    return [fn(row, th) for _, _, fn in RULES]


def first_failure(row: dict[str, Any], th: Thresholds) -> tuple[int, Outcome] | None:
    for step, _, fn in RULES:
        o = fn(row, th)
        if o != "pass":
            return step, o
    return None


def public_row(row: dict[str, Any], th: Thresholds) -> dict[str, Any]:
    return {
        "ticker": row["ticker"],
        "name": row.get("name"),
        "sector": row.get("sector"),
        "industry": row.get("industry"),
        "price": row.get("price"),
        "market_cap": row.get("market_cap"),
        "dps_ttm": _v(row, "dps_ttm", th),
        "yield": _v(row, "yield", th),
        "eps_ttm": row.get("eps_ttm"),
        "payout": _v(row, "payout", th),
        "fcf": row.get("fcf"),
        "fcf_source": row.get("fcf_source"),
        "paid_years": _v(row, "paid_years", th),
        "growth_years": _v(row, "growth_years", th),
        "has_special": bool(row.get("has_special")),
        "has_data": bool(row.get("has_data")),
    }


def run_screen(rows: list[dict[str, Any]], th: Thresholds) -> dict[str, Any]:
    funnel = [{"step": 0, "label": "Universe", "remaining": len(rows), "failed": 0, "failed_missing_data": 0}]
    survivors = rows
    for step, label, fn in RULES:
        nxt: list[dict[str, Any]] = []
        missing = failed = 0
        for r in survivors:
            o = fn(r, th)
            if o == "pass":
                nxt.append(r)
            elif o == "missing":
                missing += 1
            else:
                failed += 1
        funnel.append(
            {"step": step, "label": label, "remaining": len(nxt), "failed": failed + missing, "failed_missing_data": missing}
        )
        survivors = nxt
    results = sorted((public_row(r, th) for r in survivors), key=lambda r: -(r["yield"] or 0))
    return {"funnel": funnel, "results": results}


def eliminated_at(rows: list[dict[str, Any]], th: Thresholds, step: int) -> list[dict[str, Any]]:
    out = []
    for r in rows:
        ff = first_failure(r, th)
        if ff and ff[0] == step:
            pr = public_row(r, th)
            pr["missing_data"] = ff[1] == "missing"
            out.append(pr)
    out.sort(key=lambda r: -(r["market_cap"] or 0))
    return out


def checks(row: dict[str, Any], th: Thresholds) -> list[dict[str, Any]]:
    values = {
        1: _v(row, "yield", th),
        2: _v(row, "payout", th),
        3: row.get("fcf"),
        4: _v(row, "paid_years", th),
        5: _v(row, "growth_years", th),
    }
    thresholds = {1: th.yield_min, 2: th.payout_max, 3: th.fcf_min, 4: th.paid_years_min, 5: th.growth_years_min}
    return [
        {"step": s, "label": label, "outcome": fn(row, th), "value": values[s], "threshold": thresholds[s]}
        for s, label, fn in RULES
    ]
