"""DataProvider interface and the normalized per-ticker payload."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, TypedDict


class TickerData(TypedDict, total=False):
    ticker: str
    name: str | None
    sector: str | None
    industry: str | None
    market_cap: float | None
    price: float | None
    # [[iso_date, amount], ...]
    dividends: list[list[Any]]
    # True when dividend amounts are already split-adjusted (yfinance, FMP)
    dividends_adjusted: bool
    # [[iso_date, ratio], ...] — ratio = new shares per old share
    splits: list[list[Any]]
    eps_ttm: float | None
    ocf_ttm: float | None
    capex_ttm: float | None
    ocf_fy: float | None
    capex_fy: float | None
    # {year: value} annual histories (for the detail drawer)
    eps_history: dict[str, float]
    fcf_history: dict[str, float]
    # [[iso_date, close], ...] weekly closes for the last ~3 years
    price_history: list[list[Any]]
    # True when fundamentals were skipped because the stock pays no dividend
    fundamentals_skipped: bool


class ProviderError(Exception):
    """Raised for an unrecoverable per-ticker failure."""


class RateLimitError(ProviderError):
    """Raised when the provider signals rate limiting (retry with backoff)."""


class DataProvider(ABC):
    name: str = "base"

    @abstractmethod
    def fetch(self, ticker: str, full: bool = False) -> TickerData:
        """Fetch everything needed for one ticker.

        When ``full`` is False a provider may skip fundamentals for stocks that
        paid no dividend in the last ~13 months (they fail rule 1 regardless).
        """
