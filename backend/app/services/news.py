"""Database persistence for headlines.

Parsing, tagging and deduplication live in newsfeed.py, which has no ORM
dependency so the scheduled CI job can use it without a database.
"""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..models import Instrument, NewsItem
from .newsfeed import FEEDS, collect  # re-exported for callers

log = logging.getLogger(__name__)

__all__ = ["FEEDS", "collect", "refresh", "latest", "symbol_names"]


def symbol_names(db: Session) -> list[tuple[str, str]]:
    return [(i.symbol, i.name or "") for i in db.scalars(select(Instrument))]


def refresh(db: Session) -> dict[str, int]:
    """Fetch every feed and upsert. Failures are per-feed, never fatal."""
    items, stats = collect(symbol_names(db))
    if not items:
        return {"fetched": 0, **stats}

    stmt = pg_insert(NewsItem).values(items)
    stmt = stmt.on_conflict_do_update(
        index_elements=[NewsItem.guid],
        set_={
            "title": stmt.excluded.title,
            "summary": stmt.excluded.summary,
            "symbols": stmt.excluded.symbols,
        },
    )
    db.execute(stmt)
    db.commit()
    return {"fetched": len(items), **stats}


def latest(db: Session, limit: int = 60) -> list[dict]:
    rows = db.scalars(
        select(NewsItem).order_by(NewsItem.published_at.desc().nullslast()).limit(limit)
    ).all()
    return [
        {
            "title": n.title,
            "link": n.link,
            "source": n.source,
            "summary": (n.summary or "")[:280],
            "published_at": n.published_at.isoformat() if n.published_at else None,
            "symbols": n.symbols or [],
        }
        for n in rows
    ]
