from __future__ import annotations

from datetime import date

import pytest

from app import metrics as m
from app.compute import compute_row

AS_OF = date(2026, 11, 1)


def quarterly(year_from: int, year_to: int, amount_by_year: dict[int, float] | float) -> list[m.Payment]:
    out = []
    for y in range(year_from, year_to + 1):
        amt = amount_by_year if isinstance(amount_by_year, float) else amount_by_year[y]
        for mo in (3, 6, 9, 12):
            d = date(y, mo, 15)
            if d <= AS_OF:
                out.append((d, amt))
    return out


# ---- yield ---------------------------------------------------------------
def test_yield_basic() -> None:
    assert m.dividend_yield(2.0, 50.0) == pytest.approx(4.0)


def test_yield_no_dividends_is_zero_not_missing() -> None:
    assert m.dividend_yield(0.0, 50.0) == 0.0


def test_yield_missing_price() -> None:
    assert m.dividend_yield(2.0, None) is None
    assert m.dividend_yield(2.0, 0.0) is None


def test_ttm_window() -> None:
    pays = [(date(2025, 10, 31), 1.0), (date(2025, 11, 2), 1.0), (date(2026, 11, 1), 1.0), (date(2026, 11, 2), 9.0)]
    # (2025-11-01, 2026-11-01]
    assert m.ttm_dividends(pays, AS_OF) == pytest.approx(2.0)


# ---- payout --------------------------------------------------------------
def test_payout_basic() -> None:
    assert m.payout_ratio(1.4, 2.0) == pytest.approx(70.0)


@pytest.mark.parametrize("eps", [0.0, -1.5, None])
def test_payout_excludes_non_positive_or_missing_eps(eps: float | None) -> None:
    assert m.payout_ratio(1.0, eps) is None


# ---- FCF -----------------------------------------------------------------
def test_fcf_ttm_negative_capex_convention() -> None:
    assert m.free_cash_flow(100.0, -30.0, None, None) == (70.0, "ttm")


def test_fcf_positive_capex_convention() -> None:
    assert m.free_cash_flow(100.0, 30.0, None, None) == (70.0, "ttm")


def test_fcf_falls_back_to_fiscal_year() -> None:
    assert m.free_cash_flow(None, None, 50.0, -60.0) == (-10.0, "fy")


def test_fcf_missing() -> None:
    assert m.free_cash_flow(None, None, None, None) == (None, None)


def test_fcf_no_capex_line() -> None:
    assert m.free_cash_flow(80.0, None, None, None) == (80.0, "ttm")


# ---- streaks -------------------------------------------------------------
def test_no_dividends() -> None:
    s = m.dividend_stats([], AS_OF, ignore_specials=True)
    assert (s.dps_ttm, s.paid_years, s.growth_years) == (0.0, 0, 0)


def test_paid_streak_counts_from_last_completed_year() -> None:
    annual = {2020: 1, 2021: 1, 2022: 1, 2023: 1, 2024: 1, 2025: 1}
    assert m.paid_streak(annual, 2025) == 6


def test_missing_year_breaks_paid_streak() -> None:
    annual = {y: 1.0 for y in range(2010, 2026) if y != 2021}
    assert m.paid_streak(annual, 2025) == 4


def test_growth_streak_strict_increase() -> None:
    annual = {2019: 1.0, 2020: 1.1, 2021: 1.2, 2022: 1.3, 2023: 1.4, 2024: 1.5, 2025: 1.6}
    assert m.growth_streak(annual, 2025) == 6


def test_flat_dividend_is_not_growth() -> None:
    annual = {y: 1.0 for y in range(2010, 2026)}
    assert m.growth_streak(annual, 2025) == 0


def test_dividend_cut_breaks_growth_streak() -> None:
    annual = {2019: 1.0, 2020: 1.1, 2021: 1.2, 2022: 1.3, 2023: 0.9, 2024: 1.0, 2025: 1.1}
    assert m.growth_streak(annual, 2025) == 2
    assert m.paid_streak(annual, 2025) == 7


def test_partial_current_year_does_not_break_streaks() -> None:
    # 2026 has only 3 of 4 quarterly payments as of Nov 1 and is lower than 2025
    pays = quarterly(2015, 2026, {y: 0.25 * 1.05 ** (y - 2015) for y in range(2015, 2027)})
    s = m.dividend_stats(pays, AS_OF, ignore_specials=True)
    assert s.annual[2026] < s.annual[2025]
    assert s.paid_years == 11 and s.growth_years == 10


def test_first_dividend_year_has_no_growth() -> None:
    annual = {2024: 1.0, 2025: 1.2}
    assert m.growth_streak(annual, 2025) == 1


# ---- splits & specials ---------------------------------------------------
def test_split_adjustment() -> None:
    raw = [(date(2022, 6, 15), 1.0), (date(2022, 12, 15), 1.0), (date(2023, 6, 15), 0.55), (date(2023, 12, 15), 0.55)]
    adj = m.split_adjust(raw, [(date(2023, 1, 10), 2.0)])
    assert [a for _, a in adj] == pytest.approx([0.5, 0.5, 0.55, 0.55])
    annual = m.annual_totals(adj)
    assert m.growth_streak(annual, 2023) == 1
    # without adjusting, the split looks like a cut
    assert m.growth_streak(m.annual_totals(raw), 2023) == 0


def test_special_dividend_flagged_and_ignored() -> None:
    pays = quarterly(2018, 2025, {y: 0.25 * 1.05 ** (y - 2018) for y in range(2018, 2026)})
    pays.append((date(2024, 12, 20), 5.0))
    pays.sort()
    flags = m.special_flags(pays)
    assert sum(flags) == 1
    with_specials = m.dividend_stats(pays, AS_OF, ignore_specials=False)
    without = m.dividend_stats(pays, AS_OF, ignore_specials=True)
    assert with_specials.growth_years == 0  # 2025 < 2024 (special-inflated)
    assert without.growth_years == 7


def test_specials_need_baseline() -> None:
    assert m.special_flags([(date(2025, 1, 1), 1.0), (date(2025, 6, 1), 10.0)]) == [False, False]


# ---- compute_row integration -------------------------------------------
def test_compute_row_split_unadjusted_payload() -> None:
    payload = {
        "ticker": "X",
        "price": 50.0,
        "eps_ttm": 4.0,
        "ocf_ttm": 10.0,
        "capex_ttm": -2.0,
        "dividends_adjusted": False,
        "splits": [["2024-01-02", 2.0]],
        "dividends": [[f"{y}-{mo:02d}-15", {2024: 0.55, 2025: 0.6, 2026: 0.65}.get(y, 1.0)] for y in range(2018, 2027) for mo in (3, 9) if f"{y}-{mo:02d}-15" <= "2026-11-01"],
    }
    row = compute_row("X", payload, AS_OF)  # type: ignore[arg-type]
    # adjusted annual: 2018-23 = 1.0 (flat), 2024 = 1.1, 2025 = 1.2
    assert row["growth_years_reg"] == 2
    assert row["paid_years_reg"] == 8
    assert row["yield_reg"] == pytest.approx(1.3 / 50 * 100)
    assert row["payout_reg"] == pytest.approx(1.3 / 4.0 * 100)
    assert row["fcf"] == 8.0


def test_compute_row_no_payload_marks_missing() -> None:
    row = compute_row("Y", None, AS_OF, "Y Corp")
    assert row["has_data"] == 0 and row["name"] == "Y Corp"


def test_long_growing_history_is_not_special() -> None:
    # 40 years of 8%/yr growth: recent payments are >>3x the all-time median
    pays = quarterly(1985, 2025, {y: 0.01 * 1.08 ** (y - 1985) for y in range(1985, 2026)})
    assert not any(m.special_flags(pays))
    s = m.dividend_stats(pays, AS_OF, ignore_specials=True)
    assert s.growth_years == 40


def test_ex_date_shift_does_not_break_growth() -> None:
    # 2018 gets a 5th payment (Jan 2019 ex-date slid into Dec 2018); schedule stays shifted
    pays: list[m.Payment] = []
    for y in range(2012, 2026):
        amt = 0.25 * 1.04 ** (y - 2012)
        months = (3, 6, 9, 12) if y < 2018 else (2, 5, 8, 11)
        pays += [(date(y, mo, 15), amt) for mo in months]
    pays.append((date(2018, 1, 2), 0.25 * 1.04**5))  # late Q4-2017 payment
    pays.sort()
    s = m.dividend_stats(pays, AS_OF, ignore_specials=True)
    assert s.growth_years == 13
    assert m.dividend_stats(pays, AS_OF, ignore_specials=True, normalize_timing=False).growth_years < 13


def test_mid_year_suspension_still_breaks_growth() -> None:
    pays = quarterly(2015, 2024, {y: 0.25 * 1.05 ** (y - 2015) for y in range(2015, 2025)})
    pays += [(date(2025, 3, 15), 0.25 * 1.05**10), (date(2025, 6, 15), 0.25 * 1.05**10)]
    assert m.dividend_stats(pays, AS_OF, ignore_specials=True).growth_years == 0


def test_frequency_change_is_not_special() -> None:
    # quarterly until 2010, annual (same yearly total, growing) afterwards
    pays = quarterly(2006, 2010, {y: 0.25 * 1.05 ** (y - 2006) for y in range(2006, 2011)})
    pays += [(date(y, 11, 15), 1.05 ** (y - 2006)) for y in range(2011, 2026)]
    assert not any(m.special_flags(pays))


def test_price_change_full_window() -> None:
    pts = [(date(2023, 11, 3), 50.0), (date(2025, 1, 1), 70.0), (date(2026, 11, 1), 40.0)]
    assert m.price_change(pts) == pytest.approx(-20.0)


def test_price_change_needs_three_years() -> None:
    assert m.price_change([(date(2025, 1, 1), 50.0), (date(2026, 11, 1), 40.0)]) is None
    assert m.price_change([]) is None
