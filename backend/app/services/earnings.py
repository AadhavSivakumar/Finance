"""Earnings-date ingestion.

One yfinance call per symbol, ~0.7s each, so this runs in the daily training
cycle and never in the 15-minute refresh. Failures are per-symbol: one delisted
ticker must not abort the other 528.
"""

from __future__ import annotations

import logging
import warnings
from datetime import date

import pandas as pd
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..models import EarningsDate

log = logging.getLogger(__name__)

# ETFs, indices and crypto have no earnings. Skipping them saves ~30 useless
# network calls and avoids yfinance raising on symbols like ^VIX.
NO_EARNINGS_PREFIXES = ("^",)
NO_EARNINGS_SUFFIXES = ("-USD",)


def _has_earnings(symbol: str, group: str) -> bool:
    if group != "equity":
        return False
    if symbol.startswith(NO_EARNINGS_PREFIXES) or symbol.endswith(NO_EARNINGS_SUFFIXES):
        return False
    return True


def fetch_symbol(symbol: str, limit: int = 60) -> list[date]:
    import yfinance as yf

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        frame = yf.Ticker(symbol).get_earnings_dates(limit=limit)
    if frame is None or frame.empty:
        return []
    out: set[date] = set()
    for ts in frame.index:
        try:
            out.add(pd.Timestamp(ts).date())
        except Exception:  # noqa: BLE001
            continue
    return sorted(out)


def refresh(db: Session, symbol_groups: list[tuple[str, str]]) -> dict[str, int]:
    """Upsert earnings dates for every equity in `symbol_groups`."""
    rows: list[dict] = []
    ok = failed = 0
    for symbol, group in symbol_groups:
        if not _has_earnings(symbol, group):
            continue
        try:
            dates = fetch_symbol(symbol)
        except Exception as exc:  # noqa: BLE001
            failed += 1
            log.debug("earnings fetch failed for %s: %s", symbol, exc)
            continue
        ok += 1
        rows.extend({"symbol": symbol, "earnings_date": d} for d in dates)

    if rows:
        for i in range(0, len(rows), 5000):
            stmt = pg_insert(EarningsDate).values(rows[i : i + 5000])
            db.execute(stmt.on_conflict_do_nothing(constraint="uq_earnings_symbol_date"))
        db.commit()
    return {"symbols_ok": ok, "symbols_failed": failed, "dates": len(rows)}


def load(db: Session) -> pd.DataFrame:
    rows = db.execute(select(EarningsDate.symbol, EarningsDate.earnings_date)).all()
    if not rows:
        return pd.DataFrame(columns=["symbol", "earnings_date"])
    frame = pd.DataFrame(rows, columns=["symbol", "earnings_date"])
    frame["earnings_date"] = pd.to_datetime(frame["earnings_date"])
    return frame.sort_values(["symbol", "earnings_date"]).reset_index(drop=True)
