"""Financial Modeling Prep provider (paid API). Set FMP_API_KEY in .env and
DIVSCREEN_PROVIDER=fmp to use it.

NOTE: written against FMP's "stable" endpoints but not exercised in CI
because it needs a paid key. Field names may need adjusting for your plan.
"""

from __future__ import annotations

from typing import Any

import requests

from ..config import FMP_API_KEY
from .base import DataProvider, ProviderError, RateLimitError, TickerData

BASE = "https://financialmodelingprep.com/stable"


class FMPProvider(DataProvider):
    name = "fmp"

    def __init__(self, api_key: str | None = None, session: requests.Session | None = None) -> None:
        self.api_key = api_key or FMP_API_KEY
        if not self.api_key:
            raise ProviderError("FMP_API_KEY is not set")
        self.s = session or requests.Session()

    def _get(self, path: str, **params: Any) -> Any:
        params["apikey"] = self.api_key
        r = self.s.get(f"{BASE}/{path}", params=params, timeout=20)
        if r.status_code == 429:
            raise RateLimitError("FMP 429")
        if r.status_code >= 400:
            raise ProviderError(f"FMP {r.status_code}: {r.text[:200]}")
        return r.json()

    def fetch(self, ticker: str, full: bool = False) -> TickerData:
        sym = ticker.replace("-", ".")
        profile = (self._get("profile", symbol=sym) or [{}])[0]
        divs = self._get("dividends", symbol=sym) or []
        data: TickerData = {
            "ticker": ticker,
            "name": profile.get("companyName"),
            "sector": profile.get("sector"),
            "industry": profile.get("industry"),
            "market_cap": profile.get("marketCap"),
            "price": profile.get("price"),
            # FMP's adjDividend is split-adjusted
            "dividends": [[d["date"], float(d.get("adjDividend") or d.get("dividend") or 0)] for d in divs if d.get("date")],
            "dividends_adjusted": True,
            "splits": [],
            "eps_history": {},
            "fcf_history": {},
        }
        inc_q = self._get("income-statement", symbol=sym, period="quarter", limit=4) or []
        if len(inc_q) == 4:
            data["eps_ttm"] = sum(float(q.get("epsDiluted") or 0) for q in inc_q)
        cf_q = self._get("cash-flow-statement", symbol=sym, period="quarter", limit=4) or []
        if len(cf_q) == 4:
            data["ocf_ttm"] = sum(float(q.get("operatingCashFlow") or 0) for q in cf_q)
            data["capex_ttm"] = sum(float(q.get("capitalExpenditure") or 0) for q in cf_q)
        cf_a = self._get("cash-flow-statement", symbol=sym, limit=5) or []
        if cf_a:
            data["ocf_fy"] = cf_a[0].get("operatingCashFlow")
            data["capex_fy"] = cf_a[0].get("capitalExpenditure")
            for row in cf_a:
                data["fcf_history"][str(row.get("fiscalYear") or row["date"][:4])] = float(
                    (row.get("operatingCashFlow") or 0) - abs(row.get("capitalExpenditure") or 0)
                )
        inc_a = self._get("income-statement", symbol=sym, limit=5) or []
        for row in inc_a:
            if row.get("epsDiluted") is not None:
                data["eps_history"][str(row.get("fiscalYear") or row["date"][:4])] = float(row["epsDiluted"])
        return data
