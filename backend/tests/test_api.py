from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path: Path) -> Iterator[TestClient]:
    os.environ["DIVSCREEN_FIXTURES"] = "1"
    os.environ["DIVSCREEN_DB"] = str(tmp_path / "t.db")
    from app.main import app

    with TestClient(app) as c:
        yield c
    del os.environ["DIVSCREEN_DB"]


def tickers(res: dict) -> set[str]:
    return {r["ticker"] for r in res["results"]}


def test_default_screen(client: TestClient) -> None:
    res = client.get("/api/screen").json()
    assert [f["remaining"] for f in res["funnel"]] == [22, 18, 14, 12, 10, 8]
    assert [f["failed_missing_data"] for f in res["funnel"]] == [0, 2, 1, 1, 0, 0]
    assert tickers(res) == {"STDY", "UTIL", "PIPE", "BANK", "LEAF", "SPLT", "PART", "SPCL"}


def test_specials_toggle(client: TestClient) -> None:
    res = client.get("/api/screen", params={"ignore_specials": "false"}).json()
    assert "SPCL" not in tickers(res)


def test_relaxed_preset(client: TestClient) -> None:
    res = client.get("/api/screen", params={"yield_min": 2, "payout_max": 80, "paid_years_min": 3, "growth_years_min": 3}).json()
    assert {"YUNG", "GAPY"} <= tickers(res)


def test_eliminated(client: TestClient) -> None:
    res = client.get("/api/screen/eliminated", params={"step": 1}).json()
    assert {i["ticker"] for i in res["items"]} == {"GRWT", "LOWY", "DLST", "NOPX"}
    assert res["missing_data"] == 2


def test_stock_detail(client: TestClient) -> None:
    d = client.get("/api/stock/CUTR").json()
    assert d["growth_years"] == 2
    assert [c["outcome"] for c in d["checks"]] == ["pass", "pass", "pass", "pass", "fail"]
    assert d["annual_dividends"][-1]["year"] == 2025 or d["annual_dividends"][-1]["year"] == 2026
    assert client.get("/api/stock/NOPE").status_code == 404


def test_meta(client: TestClient) -> None:
    m = client.get("/api/meta").json()
    assert m["fixtures_mode"] and m["fetch_errors"] == 1 and m["error_tickers"][0]["ticker"] == "DLST"


def test_watchlist_flags_failures(client: TestClient) -> None:
    assert client.post("/api/watchlist/stdy").status_code == 200
    client.post("/api/watchlist/HIPO")
    items = {i["ticker"]: i for i in client.get("/api/watchlist").json()["items"]}
    assert items["STDY"]["fails"] == [] and items["HIPO"]["fails"] == [2]
    tight = {i["ticker"]: i for i in client.get("/api/watchlist", params={"yield_min": 3.5}).json()["items"]}
    assert 1 in tight["STDY"]["fails"]
    client.delete("/api/watchlist/STDY")
    assert "STDY" not in {i["ticker"] for i in client.get("/api/watchlist").json()["items"]}


def test_prices_endpoint(client: TestClient) -> None:
    p = client.get("/api/stock/STDY/prices").json()
    assert len(p["points"]) == 157 and p["source"] == "cache"
    assert p["points"][-1]["date"] == "2026-11-01"
    assert client.get("/api/stock/NOPX/prices").json()["points"] == []
    assert client.get("/api/stock/NOPE/prices").status_code == 404


def test_price_filter_rule_6(client: TestClient) -> None:
    off = client.get("/api/screen").json()
    assert len(off["funnel"]) == 6  # rule 6 only appears when enabled
    on = client.get("/api/screen", params={"price_filter": "true", "price_drop_max": 20}).json()
    assert len(on["funnel"]) == 7 and on["funnel"][6]["label"] == "Price held up"
    assert on["funnel"][5]["remaining"] == off["funnel"][5]["remaining"]
    assert all(r["price_change_3y"] >= -20 for r in on["results"])
    dropped = client.get("/api/screen/eliminated", params={"step": 6, "price_filter": "true"}).json()
    assert all(i["price_change_3y"] is None or i["price_change_3y"] < -20 for i in dropped["items"])
    assert dropped["total"] == on["funnel"][6]["failed"]
    # a looser threshold never keeps fewer
    loose = client.get("/api/screen", params={"price_filter": "true", "price_drop_max": 60}).json()
    assert loose["funnel"][6]["remaining"] >= on["funnel"][6]["remaining"]
    d = client.get("/api/stock/STDY", params={"price_filter": "true"}).json()
    assert [c["step"] for c in d["checks"]] == [1, 2, 3, 4, 5, 6]
