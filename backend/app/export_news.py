"""Export ONLY the headlines.

Split from the full export so the 5-minute news job stays cheap. The full
pipeline takes ~5 minutes of compute (ingest, features, training); headlines
take seconds. Rebuilding everything just to refresh a news feed would be
wasteful and would collide with the main deploy.

Run:  python -m app.export_news --out ./news-data
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from .db import SessionLocal
from .services import news as news_service
from .services import queries

log = logging.getLogger(__name__)


def export(out_dir: Path, limit: int = 80) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    db = SessionLocal()
    try:
        stats = news_service.refresh(db)
        items = queries.news(db, limit=limit)
    finally:
        db.close()

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "sources": stats,
        "items": items,
    }
    (out_dir / "news.json").write_text(json.dumps(payload, separators=(",", ":"), default=str))
    return len(items)


def main() -> None:
    logging.basicConfig(level="INFO", format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="./news-data")
    ap.add_argument("--limit", type=int, default=80)
    args = ap.parse_args()
    log.info("exported %d headlines", export(Path(args.out), args.limit))


if __name__ == "__main__":
    main()
