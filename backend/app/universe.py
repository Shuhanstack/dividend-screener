"""Download and filter the US listed-symbol universe from nasdaqtrader.com."""

from __future__ import annotations

import logging
import re
from pathlib import Path

import requests

from .config import DATA_DIR

log = logging.getLogger(__name__)

URLS = {
    "nasdaq": "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt",
    "other": "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt",
}
EXCHANGES = {"A": "NYSE American", "N": "NYSE", "P": "NYSE Arca", "Z": "Cboe BZX", "V": "IEX"}

# Names that indicate a non-common-stock instrument.
_EXCLUDE_NAME = re.compile(
    r"\b(warrants?|units?|rights?|preferred|pfd|preference|depositary shares? (each )?representing"
    r"|notes? due|debentures?|subordinated|trust preferred|% (senior )?notes|perpetual|"
    r"exchange[- ]traded|etn|etf)\b",
    re.IGNORECASE,
)


def _excluded_symbol(sym: str) -> bool:
    # '$' = preferred series in CQS/ACT symbology; '.W/.U/.R' suffixes = warrants/units/rights
    if "$" in sym or "^" in sym or "~" in sym:
        return True
    if re.search(r"\.(W|WS|U|R|RT)$", sym) or re.search(r"\.W[S]?\.?[A-Z]?$", sym):
        return True
    return False


def parse_file(text: str, kind: str) -> list[tuple[str, str, str]]:
    """Return (yahoo_symbol, name, exchange) tuples for common stocks."""
    lines = [l for l in text.splitlines() if l.strip()]
    header = lines[0].split("|")
    out: list[tuple[str, str, str]] = []
    for line in lines[1:]:
        if line.startswith("File Creation Time"):
            continue
        rec = dict(zip(header, line.split("|")))
        sym = rec.get("Symbol") or rec.get("ACT Symbol") or ""
        name = rec.get("Security Name", "")
        if not sym or rec.get("ETF") == "Y" or rec.get("Test Issue") == "Y" or rec.get("NextShares") == "Y":
            continue
        if _excluded_symbol(sym) or _EXCLUDE_NAME.search(name):
            continue
        if kind == "nasdaq":
            # NASDAQ 5-letter symbols with W/U/R suffix are warrants/units/rights
            if len(sym) == 5 and sym[-1] in "WUR":
                continue
            exch = "NASDAQ"
        else:
            exch = EXCHANGES.get(rec.get("Exchange", ""), rec.get("Exchange", ""))
        out.append((sym.replace(".", "-"), name.split(" - ")[0].strip(), exch))
    return out


def download_universe(cache_dir: Path = DATA_DIR) -> list[tuple[str, str, str]]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    result: dict[str, tuple[str, str, str]] = {}
    for kind, url in URLS.items():
        cache = cache_dir / f"{kind}listed.txt"
        try:
            r = requests.get(url, timeout=30, headers={"User-Agent": "dividend-screener/0.1"})
            r.raise_for_status()
            cache.write_text(r.text)
            text = r.text
        except requests.RequestException as exc:
            if not cache.exists():
                raise
            log.warning("Universe download failed (%s); using cached %s", exc, cache)
            text = cache.read_text()
        for rec in parse_file(text, kind):
            result.setdefault(rec[0], rec)
    return sorted(result.values())
