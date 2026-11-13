"""Export a static snapshot for the browser-only build (GitHub Pages).

``python -m app.export --out ../frontend/public/data [--fixtures]``

Writes:
  screen.json   meta + one compact row per ticker (columns + arrays)
  details.json  per-ticker drawer data (annual dividends, specials, histories)
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from . import config
from .db import connect, get_meta
from .screen import LIST_COLUMNS, load_rows


def _r(v: Any) -> Any:
    return round(v, 4) if isinstance(v, float) else v


def export(conn: Any, out: Path) -> dict[str, int]:
    out.mkdir(parents=True, exist_ok=True)
    rows = load_rows(conn)
    cols = [c.strip() for c in LIST_COLUMNS.split(",")]
    errors = {
        r["ticker"]: (r["error"], r["fetched_at"])
        for r in conn.execute("SELECT ticker, error, fetched_at FROM raw_data")
    }
    meta = {
        "last_refresh": get_meta(conn, "last_refresh"),
        "as_of": get_meta(conn, "as_of"),
        "provider": get_meta(conn, "provider"),
        "fixtures_mode": get_meta(conn, "provider") == "fixtures",
        "universe_size": int(get_meta(conn, "universe_size") or 0),
        "screened": len(rows),
        "fetch_errors": sum(1 for e, _ in errors.values() if e),
        "stale_count": sum(1 for r in rows if r.get("stale")),
        "not_refreshed_count": sum(1 for r in rows if r.get("stale") == '["all"]'),
        "error_tickers": [
            {"ticker": t, "error": e, "fetched_at": f} for t, (e, f) in sorted(errors.items()) if e
        ][:500],
        "static": True,
    }
    screen = {"meta": meta, "columns": cols, "rows": [[_r(r[c]) for c in cols] for r in rows]}
    (out / "screen.json").write_text(json.dumps(screen, separators=(",", ":")))

    details: dict[str, Any] = {}
    for r in conn.execute("SELECT ticker, detail FROM metrics"):
        d = json.loads(r["detail"] or "{}")
        err, fetched = errors.get(r["ticker"], (None, None))
        if not d and not err:
            continue
        d["fetched_at"] = fetched
        d["fetch_error"] = err
        d.pop("recent_payments", None)
        d.pop("ocf", None)
        d.pop("capex", None)
        details[r["ticker"]] = d
    (out / "details.json").write_text(json.dumps(details, separators=(",", ":")))
    return {"rows": len(rows), "details": len(details)}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--fixtures", action="store_true")
    args = ap.parse_args(argv)
    if args.fixtures:
        from .refresh import build_fixture_db

        conn = build_fixture_db()
    else:
        conn = connect(config.db_path(False))
    n = export(conn, args.out)
    print(f"Exported {n['rows']:,} rows and {n['details']:,} detail records to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
