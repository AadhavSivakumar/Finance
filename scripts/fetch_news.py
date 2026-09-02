"""Standalone headline fetcher for the scheduled CI job.

Imports only `app.services.newsfeed`, which has no ORM dependency, so this runs
with httpx alone -- no database, no pandas, no scikit-learn. That is what keeps
a 5-minute job to a few seconds instead of several minutes.

Ticker names come from a JSON file produced by the main build, so tagging stays
consistent with the dashboard without needing the database that produced it.

Usage:
  python scripts/fetch_news.py --out site-data --symbols site-data/symbols.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services import newsfeed  # noqa: E402

log = logging.getLogger("fetch_news")


def load_symbol_names(path: Path | None) -> list[tuple[str, str]]:
    if not path or not path.exists():
        log.warning("no symbols file at %s — headlines will be untagged", path)
        return []
    data = json.loads(path.read_text())
    return [(row["symbol"], row.get("name", "")) for row in data]


def main() -> int:
    logging.basicConfig(level="INFO", format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--symbols")
    ap.add_argument("--limit", type=int, default=80)
    args = ap.parse_args()

    names = load_symbol_names(Path(args.symbols) if args.symbols else None)
    items, stats = newsfeed.collect(names)

    if not items:
        # Never overwrite a good file with an empty one: a transient feed
        # outage would otherwise blank the news panel until the next run.
        log.error("no headlines fetched from any feed: %s", stats)
        return 1

    # Newest first; undated items sort last rather than jumping to the top.
    items.sort(key=lambda i: i.get("published_at") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": stats,
        "items": [
            {
                "title": i["title"],
                "link": i["link"],
                "source": i["source"],
                "summary": i["summary"][:280],
                "published_at": i["published_at"].isoformat() if i["published_at"] else None,
                "symbols": i["symbols"],
            }
            for i in items[: args.limit]
        ],
    }
    (out_dir / "news.json").write_text(json.dumps(payload, separators=(",", ":"), default=str))
    log.info("wrote %d headlines from %s", len(payload["items"]), stats)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
