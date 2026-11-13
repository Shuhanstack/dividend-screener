"""Offline provider that serves JSON files from tests/fixtures."""

from __future__ import annotations

import json
from pathlib import Path

from ..config import FIXTURES_DIR
from .base import DataProvider, ProviderError, TickerData


class FixtureProvider(DataProvider):
    name = "fixtures"

    def __init__(self, directory: Path = FIXTURES_DIR) -> None:
        self.dir = directory / "tickers"

    def tickers(self) -> list[tuple[str, str]]:
        out = []
        for p in sorted(self.dir.glob("*.json")):
            d = json.loads(p.read_text())
            out.append((d["ticker"], d.get("name") or d["ticker"]))
        return out

    def fetch(self, ticker: str, full: bool = False) -> TickerData:
        p = self.dir / f"{ticker}.json"
        if not p.exists():
            raise ProviderError(f"no fixture for {ticker}")
        d: TickerData = json.loads(p.read_text())
        if d.get("_simulate_error"):  # type: ignore[typeddict-item]
            raise ProviderError(str(d["_simulate_error"]))  # type: ignore[typeddict-item]
        return d
