"""Pure metric calculations for the 5 dividend rules.

Everything here is side-effect free and operates on plain Python data so it
can be unit-tested without a network or database.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from statistics import median
from typing import Iterable, Sequence

Payment = tuple[date, float]
"""A single dividend payment: (ex-date, amount per share)."""

SPECIAL_FACTOR = 3.0
_EPS = 1e-9


# --------------------------------------------------------------------------- #
# Dividend history helpers
# --------------------------------------------------------------------------- #
def split_adjust(payments: Sequence[Payment], splits: Sequence[tuple[date, float]]) -> list[Payment]:
    """Return split-adjusted payments.

    ``splits`` holds (date, ratio) pairs where ratio is new shares per old share
    (e.g. 2.0 for a 2-for-1). Every payment *before* a split is divided by that
    split's ratio so that all amounts are expressed per current share.
    """
    out: list[Payment] = []
    for d, amt in payments:
        factor = 1.0
        for sd, ratio in splits:
            if ratio and ratio > 0 and d < sd:
                factor *= ratio
        out.append((d, amt / factor))
    return out


def special_flags(
    payments: Sequence[Payment], factor: float = SPECIAL_FACTOR, window_days: int = 730
) -> list[bool]:
    """Flag one-off special dividends.

    A payment is "special" when it is more than ``factor`` x the median of the
    stock's *other* payments within +/- ``window_days`` of it. A local median
    is used because long histories of growing dividends would otherwise make
    every recent payment look large next to a decades-old all-time median.
    With fewer than 3 neighbouring payments there is no meaningful baseline,
    so the payment is not flagged.
    """
    window = timedelta(days=window_days)
    flags: list[bool] = []
    for i, (d, a) in enumerate(payments):
        before = [x for j, (dd, x) in enumerate(payments) if j != i and x > 0 and d - window <= dd <= d]
        after = [x for j, (dd, x) in enumerate(payments) if j != i and x > 0 and d <= dd <= d + window]
        sides = [side for side in (before, after) if side]
        # must stand out against every side that has a baseline; this avoids
        # flagging a switch from quarterly to annual payments as "special"
        flags.append(len(before) + len(after) >= 3 and bool(sides) and all(a > factor * median(sd) for sd in sides))
    return flags


def regular_payments(payments: Sequence[Payment], factor: float = SPECIAL_FACTOR) -> list[Payment]:
    flags = special_flags(payments, factor)
    return [p for p, special in zip(payments, flags) if not special]


def ttm_dividends(payments: Iterable[Payment], as_of: date) -> float:
    """Sum of payments with ex-date in the 365 days ending ``as_of`` (inclusive)."""
    start = as_of - timedelta(days=365)
    return float(sum(a for d, a in payments if start < d <= as_of))


def annual_totals(payments: Iterable[Payment]) -> dict[int, float]:
    totals: dict[int, float] = {}
    for d, a in payments:
        totals[d.year] = totals.get(d.year, 0.0) + a
    return {y: round(v, 6) for y, v in sorted(totals.items())}


def payment_counts(payments: Iterable[Payment]) -> dict[int, int]:
    counts: dict[int, int] = {}
    for d, a in payments:
        if a > 0:
            counts[d.year] = counts.get(d.year, 0) + 1
    return counts


def timing_normalized(
    annual: dict[int, float], counts: dict[int, int], medians: dict[int, float] | None = None
) -> dict[int, float]:
    """Correct annual totals for ex-date timing shifts.

    Calendar-year bucketing breaks when an ex-date slides across Jan 1 (e.g.
    5 quarterly payments in one year, 3 in the next). For each year we take the
    usual frequency ``f`` (median count of the surrounding +/-2 years) and,
    when the year has *extra* payments (or fewer payments offset by a
    neighbouring year with extras), replace its total with
    ``median payment x f`` — robust to a stray off-schedule entry too.
    A genuine mid-year suspension (fewer payments, no offsetting neighbour) is
    left untouched so it still counts as a cut.
    """
    out: dict[int, float] = {}
    for y, total in annual.items():
        n = counts.get(y, 0)
        around = [counts[k] for k in range(y - 2, y + 3) if counts.get(k, 0) > 0]
        if n == 0 or not around:
            out[y] = total
            continue
        f = round(median(around))
        offset = counts.get(y - 1, 0) > f or counts.get(y + 1, 0) > f
        if f > 0 and (n > f or (n < f and offset)):
            per = medians[y] if medians and y in medians else total / n
            out[y] = round(per * f, 6)
        else:
            out[y] = total
    return out


def payment_medians(payments: Iterable[Payment]) -> dict[int, float]:
    by_year: dict[int, list[float]] = {}
    for d, a in payments:
        if a > 0:
            by_year.setdefault(d.year, []).append(a)
    return {y: median(v) for y, v in by_year.items()}


def last_completed_year(as_of: date) -> int:
    return as_of.year - 1


def paid_streak(annual: dict[int, float], last_year: int) -> int:
    """Consecutive calendar years with total dividends > 0, counting back from
    ``last_year`` (the last completed year). A missing year breaks the streak."""
    n = 0
    y = last_year
    while annual.get(y, 0.0) > _EPS:
        n += 1
        y -= 1
    return n


def growth_streak(annual: dict[int, float], last_year: int) -> int:
    """Consecutive years where the annual total is strictly greater than the
    prior year's total, counting back from ``last_year``."""
    n = 0
    y = last_year
    while True:
        cur = annual.get(y, 0.0)
        prev = annual.get(y - 1, 0.0)
        if cur > _EPS and prev > _EPS and cur > prev + _EPS:
            n += 1
            y -= 1
        else:
            return n


# --------------------------------------------------------------------------- #
# Ratio metrics
# --------------------------------------------------------------------------- #
def dividend_yield(dps_ttm: float | None, price: float | None) -> float | None:
    """Yield as a percentage. None when price is unknown."""
    if price is None or price <= 0 or dps_ttm is None:
        return None
    return dps_ttm / price * 100.0


def payout_ratio(dps_ttm: float | None, eps_ttm: float | None) -> float | None:
    """Payout ratio as a percentage. None when EPS is missing or <= 0."""
    if dps_ttm is None or eps_ttm is None or eps_ttm <= 0:
        return None
    return dps_ttm / eps_ttm * 100.0


def free_cash_flow(
    ocf_ttm: float | None,
    capex_ttm: float | None,
    ocf_fy: float | None,
    capex_fy: float | None,
) -> tuple[float | None, str | None]:
    """FCF = operating cash flow - capital expenditures.

    Capex may be reported as a negative number (yfinance) or positive (some
    APIs); its magnitude is always subtracted. Missing capex is treated as 0
    only if OCF is present (many financials report no capex line).
    Returns (fcf, source) where source is "ttm", "fy" or None.
    """
    if ocf_ttm is not None:
        return ocf_ttm - abs(capex_ttm or 0.0), "ttm"
    if ocf_fy is not None:
        return ocf_fy - abs(capex_fy or 0.0), "fy"
    return None, None


def price_change(points: Sequence[tuple[date, float]], years: int = 3, slack_days: int = 30) -> float | None:
    """Percent change from the first to the last close over ``years``.

    Returns None when the history does not span (almost) the full period,
    e.g. a stock listed less than 3 years ago.
    """
    pts = [(d, c) for d, c in points if c and c > 0]
    if len(pts) < 2:
        return None
    (d0, c0), (d1, c1) = pts[0], pts[-1]
    if (d1 - d0).days < years * 365 - slack_days:
        return None
    return (c1 / c0 - 1.0) * 100.0


# --------------------------------------------------------------------------- #
# Aggregate
# --------------------------------------------------------------------------- #
@dataclass
class DividendStats:
    dps_ttm: float
    annual: dict[int, float]
    paid_years: int
    growth_years: int


def dividend_stats(
    payments: Sequence[Payment], as_of: date, ignore_specials: bool, normalize_timing: bool = True
) -> DividendStats:
    regular = regular_payments(payments)
    pays = regular if ignore_specials else list(payments)
    annual = annual_totals(pays)
    ly = last_completed_year(as_of)
    # counts use regular payments only, so an included special still lifts that year's total
    basis = timing_normalized(annual, payment_counts(regular), payment_medians(pays)) if normalize_timing else annual
    return DividendStats(
        dps_ttm=ttm_dividends(pays, as_of),
        annual=annual,
        paid_years=paid_streak(annual, ly),
        growth_years=growth_streak(basis, ly),
    )
