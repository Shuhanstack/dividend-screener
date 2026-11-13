"""Default provider: Yahoo Finance via the unofficial ``yfinance`` package."""

from __future__ import annotations

import logging
import math
from datetime import date, timedelta
from typing import Any

import pandas as pd

from .base import DataProvider, ProviderError, RateLimitError, TickerData

log = logging.getLogger(__name__)
logging.getLogger("yfinance").setLevel(logging.CRITICAL)


def _num(v: Any) -> float | None:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if math.isnan(f) or math.isinf(f) else f


def _row(df: pd.DataFrame | None, *names: str) -> pd.Series | None:
    if df is None or df.empty:
        return None
    for n in names:
        if n in df.index:
            return df.loc[n]
    return None


def _first(s: pd.Series | None) -> float | None:
    if s is None:
        return None
    for v in s.tolist():  # columns are newest first
        f = _num(v)
        if f is not None:
            return f
    return None


PRICE_YEARS = 3


def weekly_closes(closes: pd.Series, years: int = PRICE_YEARS) -> list[list[Any]]:
    """Last ``years`` of daily closes, downsampled to the last close of each week."""
    closes = closes.dropna()
    if closes.empty:
        return []
    idx = closes.index
    if getattr(idx, "tz", None) is not None:
        closes = closes.tz_localize(None)
    end = closes.index[-1]
    recent = closes[closes.index > end - pd.DateOffset(years=years)]
    weekly = recent.groupby(recent.index.to_period("W-FRI")).tail(1)
    return [[ts.date().isoformat(), round(float(v), 4)] for ts, v in weekly.items()]


def fetch_price_history(ticker: str, years: int = PRICE_YEARS) -> list[list[Any]]:
    """Standalone price-history fetch (used to backfill older cached payloads)."""
    import yfinance as yf

    try:
        hist = yf.Ticker(ticker).history(period=f"{years + 1}y", auto_adjust=False, raise_errors=True)
    except Exception as exc:  # noqa: BLE001
        raise _wrap(exc) from exc
    return weekly_closes(hist["Close"], years) if hist is not None and not hist.empty else []


def _wrap(exc: Exception) -> Exception:
    msg = f"{type(exc).__name__}: {exc}"
    if "RateLimit" in type(exc).__name__ or "Too Many Requests" in str(exc) or "429" in str(exc):
        return RateLimitError(msg)
    return ProviderError(msg)


class YFinanceProvider(DataProvider):
    name = "yfinance"

    def fetch(self, ticker: str, full: bool = False) -> TickerData:
        import yfinance as yf

        t = yf.Ticker(ticker)
        try:
            hist = t.history(period="max", auto_adjust=False, actions=True, raise_errors=True)
        except Exception as exc:  # noqa: BLE001 - yfinance raises many types
            raise _wrap(exc) from exc
        if hist is None or hist.empty:
            raise ProviderError("no price history")

        closes = hist["Close"].dropna()
        price = _num(closes.iloc[-1]) if not closes.empty else None
        divs = hist["Dividends"][hist["Dividends"] > 0] if "Dividends" in hist else pd.Series(dtype=float)
        splits = hist["Stock Splits"][hist["Stock Splits"] > 0] if "Stock Splits" in hist else pd.Series(dtype=float)

        data: TickerData = {
            "ticker": ticker,
            "price": price,
            # yfinance's history() dividends are already split-adjusted
            "dividends": [[ts.date().isoformat(), float(v)] for ts, v in divs.items()],
            "dividends_adjusted": True,
            "splits": [[ts.date().isoformat(), float(v)] for ts, v in splits.items()],
            "eps_history": {},
            "fcf_history": {},
            "price_history": weekly_closes(hist["Close"]),
        }

        recent_div = any(
            date.fromisoformat(d) > date.today() - timedelta(days=400) for d, _ in data["dividends"]
        )
        if not full and not recent_div:
            data["fundamentals_skipped"] = True
            return data

        try:
            info = t.info or {}
        except Exception as exc:  # noqa: BLE001
            raise _wrap(exc) from exc
        data["name"] = info.get("longName") or info.get("shortName")
        data["sector"] = info.get("sector")
        data["industry"] = info.get("industry")
        data["market_cap"] = _num(info.get("marketCap"))
        data["price"] = _num(info.get("currentPrice")) or _num(info.get("regularMarketPrice")) or price
        data["eps_ttm"] = _num(info.get("trailingEps"))
        if info.get("quoteType") in ("ETF", "MUTUALFUND"):
            # funds publish no income/cash-flow statements on Yahoo: skip 3 requests
            data["quote_type"] = info.get("quoteType")
            return data

        # Statements: failures here are non-fatal (metric becomes missing).
        try:
            ttm_cf = t.ttm_cashflow
            data["ocf_ttm"] = _first(_row(ttm_cf, "Operating Cash Flow", "Cash Flow From Continuing Operating Activities"))
            data["capex_ttm"] = _first(_row(ttm_cf, "Capital Expenditure"))
        except Exception as exc:  # noqa: BLE001
            if isinstance(_wrap(exc), RateLimitError):
                raise _wrap(exc) from exc
            log.debug("%s ttm cashflow: %s", ticker, exc)
        try:
            cf = t.cashflow
            ocf = _row(cf, "Operating Cash Flow", "Cash Flow From Continuing Operating Activities")
            capex = _row(cf, "Capital Expenditure")
            data["ocf_fy"] = _first(ocf)
            data["capex_fy"] = _first(capex)
            if ocf is not None:
                for col, v in ocf.items():
                    o = _num(v)
                    if o is None:
                        continue
                    c = _num(capex[col]) if capex is not None and col in capex else 0.0
                    data["fcf_history"][str(pd.Timestamp(col).year)] = o - abs(c or 0.0)
        except Exception as exc:  # noqa: BLE001
            if isinstance(_wrap(exc), RateLimitError):
                raise _wrap(exc) from exc
            log.debug("%s annual cashflow: %s", ticker, exc)
        try:
            inc = t.income_stmt
            eps = _row(inc, "Diluted EPS", "Basic EPS")
            if eps is not None:
                for col, v in eps.items():
                    e = _num(v)
                    if e is not None:
                        data["eps_history"][str(pd.Timestamp(col).year)] = e
            if data.get("eps_ttm") is None:
                ttm_inc = t.ttm_income_stmt
                data["eps_ttm"] = _first(_row(ttm_inc, "Diluted EPS", "Basic EPS"))
        except Exception as exc:  # noqa: BLE001
            if isinstance(_wrap(exc), RateLimitError):
                raise _wrap(exc) from exc
            log.debug("%s income stmt: %s", ticker, exc)
        return data
