"""Export every computed artefact as static JSON.

This is what makes GitHub Pages possible. Pages serves static files only -- no
Python, no Postgres, no worker -- but this dashboard is entirely read-only and
already precomputed, so a dump of the results is a complete, faithful copy of
what the API would serve.

Run:  python -m app.export --out ./site-data
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from .db import SessionLocal
from .services import queries

log = logging.getLogger(__name__)

# Symbols whose price history is bundled for sparklines/detail charts. Bundling
# all 529 would be ~40MB of JSON; these are the ones the UI actually plots.
HISTORY_SYMBOLS = [
    "SPY", "QQQ", "IWM", "^VIX", "TLT", "GLD", "BTC-USD", "ETH-USD",
    "XLK", "XLF", "XLE", "XLV", "XLY", "XLP", "XLI", "XLB", "XLU", "XLRE", "XLC",
]


def build_payload(db) -> dict[str, object]:
    """One dict per output file."""
    return {
        "meta": {
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "as_of": (queries.latest_as_of(db) or "").__str__() or None,
            "freshness": queries.freshness(db),
        },
        "regime": queries.regime(db),
        "movers": queries.movers(db),
        "sectors": queries.sector_rotation(db),
        "signals": queries.signals(db, days=5, limit=500),
        "models": queries.model_runs(db),
        "predictions": {
            "spike_2atr": queries.predictions(db, target="spike_2atr", limit=50),
            "up_5d": queries.predictions(db, target="up_5d", limit=50),
        },
        "correlations": queries.correlations(db),
        "news": queries.news(db, limit=80),
        "metrics": queries.metrics(),
        "symbols": queries.symbols(db),
        "macro": queries.macro(db),
        "history": {s: queries.history(db, s, days=400) for s in HISTORY_SYMBOLS},
    }


def export(out_dir: Path) -> dict[str, int]:
    out_dir.mkdir(parents=True, exist_ok=True)
    db = SessionLocal()
    try:
        payload = build_payload(db)
    finally:
        db.close()

    sizes: dict[str, int] = {}
    for name, value in payload.items():
        path = out_dir / f"{name}.json"
        # separators= trims the ~15% of bytes that default spacing adds; this
        # is served over the network on every page load.
        text = json.dumps(value, separators=(",", ":"), default=str)
        path.write_text(text)
        sizes[name] = len(text)

    # A single combined file too, so the app can do one request instead of ten.
    combined = out_dir / "all.json"
    text = json.dumps(payload, separators=(",", ":"), default=str)
    combined.write_text(text)
    sizes["all"] = len(text)
    return sizes


def main() -> None:
    logging.basicConfig(level="INFO", format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="./site-data", help="output directory")
    args = ap.parse_args()

    sizes = export(Path(args.out))
    total = sum(v for k, v in sizes.items() if k != "all")
    for name, size in sorted(sizes.items(), key=lambda kv: -kv[1]):
        log.info("%-14s %8.1f KB", name, size / 1024)
    log.info("total (excluding all.json): %.1f KB", total / 1024)


if __name__ == "__main__":
    main()
