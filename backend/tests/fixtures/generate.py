"""Generate the offline fixture dataset (synthetic companies, NOT real data).

Run: ``python tests/fixtures/generate.py`` from backend/. Output is committed so
tests and --fixtures mode work fully offline.

Each fictional ticker is designed to exercise one rule or edge case.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

AS_OF = date(2026, 11, 1)
OUT = Path(__file__).parent / "tickers"


@dataclass
class Spec:
    ticker: str
    name: str
    sector: str
    industry: str
    note: str
    start: int | None = 2000  # first dividend year (None = never paid)
    base: float = 1.0  # annual DPS in start year
    growth: float = 0.05  # per-year growth
    freq: int = 4  # payments per year
    yield_pct: float | None = 3.5  # target TTM yield -> derives price
    payout_pct: float | None = 60.0  # target payout -> derives EPS
    eps_override: float | None = None
    eps_missing: bool = False
    price_missing: bool = False
    ocf: float | None = 5e9
    capex: float | None = -1e9
    ocf_fy_only: bool = False
    market_cap: float = 5e10
    gaps: list[int] = field(default_factory=list)  # years with no dividends
    overrides: dict[int, float] = field(default_factory=dict)  # year -> annual DPS
    specials: list[tuple[str, float]] = field(default_factory=list)
    split: tuple[str, float] | None = None  # store UNadjusted amounts with this split
    partial_2026: int | None = None  # number of 2026 payments made so far
    error: str | None = None


MONTHS = {1: [6], 2: [3, 9], 4: [3, 6, 9, 12], 12: list(range(1, 13))}

SPECS: list[Spec] = [
    # ---- survivors under default rules --------------------------------------
    Spec("STDY", "Steady Beverage Co", "Consumer Defensive", "Beverages", "Classic 25+ yr grower", 1990, 0.40, 0.06, yield_pct=3.2, payout_pct=65, market_cap=2.6e11),
    Spec("UTIL", "Prairie Utility Holdings", "Utilities", "Utilities - Regulated Electric", "Steady utility", 2002, 1.10, 0.045, yield_pct=4.1, payout_pct=62, market_cap=4.1e10),
    Spec("PIPE", "Midland Pipeline Partners", "Energy", "Oil & Gas Midstream", "High-yield midstream, 8y growth", 2010, 1.50, 0.05, yield_pct=6.5, payout_pct=68, overrides={2017: 1.50 * 1.05**6}, market_cap=3.0e10),
    Spec("BANK", "Harbor Savings Bank", "Financial Services", "Banks - Regional", "No capex line (FCF = OCF)", 2005, 0.60, 0.07, yield_pct=3.5, payout_pct=40, capex=None, market_cap=1.2e10),
    Spec("LEAF", "Leaf & Ember Co", "Consumer Defensive", "Tobacco", "Very high yield, payout near cap", 2008, 2.00, 0.04, yield_pct=7.0, payout_pct=69, market_cap=8.0e10),
    Spec("SPLT", "Split Industries", "Industrials", "Specialty Industrial Machinery", "2:1 split in 2023; raw amounts unadjusted", 2008, 1.20, 0.06, yield_pct=3.1, payout_pct=55, split=("2023-05-01", 2.0)),
    Spec("PART", "Partial Year Corp", "Healthcare", "Drug Manufacturers", "Semi-annual payer, only 1 of 2 2026 payments made", 2004, 1.00, 0.05, freq=2, yield_pct=3.8, payout_pct=50, partial_2026=1),
    Spec("SPCL", "Special Payout Group", "Consumer Cyclical", "Specialty Retail", "$6 special in 2024; passes only when specials ignored", 2010, 1.00, 0.06, yield_pct=3.4, payout_pct=45, specials=[("2024-12-20", 6.0)]),
    # ---- fail rule 1 ---------------------------------------------------------
    Spec("GRWT", "Growth Cloud Inc", "Technology", "Software - Infrastructure", "Never paid a dividend", None, yield_pct=None, payout_pct=None, eps_override=4.2, market_cap=9.0e11),
    Spec("LOWY", "Lowyield Software", "Technology", "Software - Application", "Grower but 0.6% yield", 2014, 0.5, 0.10, yield_pct=0.6, payout_pct=20, market_cap=3.0e11),
    Spec("DLST", "Delisted Holdings", "Industrials", "Conglomerates", "Fetch fails (simulated) -> missing data at rule 1", error="no price history (possibly delisted)"),
    Spec("NOPX", "No Price Ltd", "Basic Materials", "Chemicals", "Price missing -> missing data at rule 1", 2005, 1.0, 0.05, price_missing=True),
    # ---- fail rule 2 ---------------------------------------------------------
    Spec("NEGE", "Negative Telecom", "Communication Services", "Telecom Services", "Negative EPS", 2000, 1.5, 0.03, yield_pct=6.0, eps_override=-1.2, market_cap=1.5e11),
    Spec("HIPO", "High Payout Chemicals", "Basic Materials", "Chemicals", "Payout 95%", 2001, 1.2, 0.05, yield_pct=5.0, payout_pct=95),
    Spec("RLTY", "Monthly Realty Trust", "Real Estate", "REIT - Retail", "Monthly REIT; EPS payout > 100% (common for REITs)", 1998, 1.8, 0.035, freq=12, yield_pct=5.6, payout_pct=230, market_cap=4.8e10),
    Spec("NOEP", "No EPS Data Inc", "Industrials", "Railroads", "EPS missing -> missing data at rule 2", 2003, 1.0, 0.05, eps_missing=True),
    # ---- fail rule 3 ---------------------------------------------------------
    Spec("BURN", "Burnrate Airlines", "Industrials", "Airlines", "Negative free cash flow", 2006, 0.8, 0.05, yield_pct=3.5, payout_pct=50, ocf=2e9, capex=-3.5e9),
    Spec("NOCF", "No Cashflow Corp", "Utilities", "Utilities - Diversified", "Cash flow missing -> missing data at rule 3", 2003, 1.0, 0.05, ocf=None, capex=None),
    # ---- fail rule 4 ---------------------------------------------------------
    Spec("YUNG", "Young Payer Co", "Technology", "Semiconductors", "Initiated dividend in 2022 (4 yrs)", 2022, 1.0, 0.08, yield_pct=3.3, payout_pct=35, ocf_fy_only=True),
    Spec("GAPY", "Gap Year Industries", "Industrials", "Engineering & Construction", "Skipped 2021 -> paid streak 4", 2005, 1.0, 0.05, gaps=[2021]),
    # ---- fail rule 5 ---------------------------------------------------------
    Spec("CUTR", "Cutter Energy", "Energy", "Oil & Gas Integrated", "Cut dividend in 2023 -> growth streak 2", 2000, 1.0, 0.06, yield_pct=4.5, payout_pct=55, overrides={2023: 1.0 * 1.06**22}),
    Spec("FLAT", "Flatline Insurance", "Financial Services", "Insurance - Life", "Flat dividend -> growth streak 0", 2005, 2.0, 0.0, yield_pct=4.0, payout_pct=50),
]


def annual_dps(s: Spec, year: int) -> float:
    assert s.start is not None
    if year in s.overrides:
        return s.overrides[year]
    return s.base * (1 + s.growth) ** (year - s.start)


def synthetic_prices(ticker: str, last: float, weeks: int = 157) -> list[list]:
    """Seeded random walk ending at ``last`` (synthetic, for offline demos)."""
    import random

    rng = random.Random(sum(ord(c) * (i + 1) for i, c in enumerate(ticker)))
    vals = [last]
    for _ in range(weeks - 1):
        vals.append(vals[-1] / (1 + rng.gauss(0.0015, 0.025)))
    vals.reverse()
    days = [AS_OF - timedelta(days=7 * (weeks - 1 - i)) for i in range(weeks)]
    return [[d.isoformat(), round(v, 2)] for d, v in zip(days, vals)]


def build(s: Spec) -> dict:
    d: dict = {
        "ticker": s.ticker,
        "name": s.name,
        "sector": s.sector,
        "industry": s.industry,
        "market_cap": s.market_cap,
        "_note": s.note,
        "dividends_adjusted": s.split is None,
        "splits": [[s.split[0], s.split[1]]] if s.split else [],
        "dividends": [],
        "eps_history": {},
        "fcf_history": {},
    }
    if s.error:
        d["_simulate_error"] = s.error
        return d
    payments: list[tuple[date, float]] = []
    if s.start is not None:
        for y in range(s.start, AS_OF.year + 1):
            if y in s.gaps:
                continue
            months = MONTHS[s.freq]
            amt = round(annual_dps(s, y) / s.freq, 4)
            if y == AS_OF.year and s.partial_2026 is not None:
                months = months[: s.partial_2026]
            for mth in months:
                pd_ = date(y, mth, 15)
                if pd_ <= AS_OF:
                    payments.append((pd_, amt))
        regular = list(payments)
        for ds, amt in s.specials:
            payments.append((date.fromisoformat(ds), amt))
        payments.sort()
    else:
        regular = []
    window_start = AS_OF - timedelta(days=365)
    ttm = sum(a for p, a in regular if window_start < p <= AS_OF)
    if s.split:
        sd, ratio = date.fromisoformat(s.split[0]), s.split[1]
        # store raw (unadjusted) amounts: pre-split payments were `ratio` x larger
        payments = [(p, round(a * ratio, 4) if p < sd else a) for p, a in payments]
    d["dividends"] = [[p.isoformat(), a] for p, a in payments]

    price = round(ttm / (s.yield_pct / 100), 2) if s.yield_pct and ttm else 85.0
    d["price"] = None if s.price_missing else price
    if s.eps_missing:
        d["eps_ttm"] = None
    elif s.eps_override is not None:
        d["eps_ttm"] = s.eps_override
    else:
        d["eps_ttm"] = round(ttm / (s.payout_pct / 100), 2) if s.payout_pct and ttm else 3.0
    d["price_history"] = [] if s.price_missing else synthetic_prices(s.ticker, price)
    if s.ocf_fy_only:
        d["ocf_ttm"], d["capex_ttm"], d["ocf_fy"], d["capex_fy"] = None, None, s.ocf, s.capex
    else:
        d["ocf_ttm"], d["capex_ttm"] = s.ocf, s.capex
        d["ocf_fy"] = s.ocf * 0.95 if s.ocf else None
        d["capex_fy"] = s.capex * 0.95 if s.capex else None
    for i, y in enumerate(range(AS_OF.year - 4, AS_OF.year)):
        if d["eps_ttm"] is not None:
            d["eps_history"][str(y)] = round(d["eps_ttm"] * (0.85 + 0.04 * i), 2)
        if s.ocf is not None:
            d["fcf_history"][str(y)] = (s.ocf - abs(s.capex or 0)) * (0.85 + 0.04 * i)
    return d


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for f in OUT.glob("*.json"):
        f.unlink()
    for s in SPECS:
        (OUT / f"{s.ticker}.json").write_text(json.dumps(build(s), indent=1))
    (OUT.parent / "manifest.json").write_text(
        json.dumps({"as_of": AS_OF.isoformat(), "synthetic": True, "tickers": [s.ticker for s in SPECS]}, indent=1)
    )
    print(f"wrote {len(SPECS)} fixtures to {OUT}")


if __name__ == "__main__":
    main()
