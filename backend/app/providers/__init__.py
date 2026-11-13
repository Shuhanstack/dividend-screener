from __future__ import annotations

from .base import DataProvider, ProviderError, RateLimitError, TickerData


def get_provider(name: str, fixtures: bool = False) -> DataProvider:
    if fixtures or name == "fixtures":
        from .fixture_provider import FixtureProvider

        return FixtureProvider()
    if name == "fmp":
        from .fmp_provider import FMPProvider

        return FMPProvider()
    from .yfinance_provider import YFinanceProvider

    return YFinanceProvider()


__all__ = ["DataProvider", "ProviderError", "RateLimitError", "TickerData", "get_provider"]
