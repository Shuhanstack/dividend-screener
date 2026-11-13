from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent.parent
ROOT_DIR = BACKEND_DIR.parent
load_dotenv(ROOT_DIR / ".env")

DATA_DIR = Path(os.getenv("DIVSCREEN_DATA_DIR", BACKEND_DIR / "data"))
FIXTURES_DIR = BACKEND_DIR / "tests" / "fixtures"


def fixtures_mode() -> bool:
    return os.getenv("DIVSCREEN_FIXTURES", "").lower() in {"1", "true", "yes"}


def db_path(fixtures: bool | None = None) -> Path:
    if fixtures is None:
        fixtures = fixtures_mode()
    override = os.getenv("DIVSCREEN_DB")
    if override:
        return Path(override)
    return DATA_DIR / ("fixtures.db" if fixtures else "screener.db")


PROVIDER = os.getenv("DIVSCREEN_PROVIDER", "yfinance")  # yfinance | fmp
FMP_API_KEY = os.getenv("FMP_API_KEY", "")
