"""Universe and price-bar ingestion.

Two jobs:

* keep ``instruments`` in step with the configured universe;
* keep ``price_bars`` topped up, fetching only what is missing.

The incremental fetch is what makes a 500-symbol universe practical. A full
8-year history is ~1.5M bars and one slow download; after that each run asks
only for bars newer than the newest one stored, which is a handful of rows.
Combined with yfinance's batch download (many symbols per HTTP request), a
daily refresh costs a few requests rather than a few hundred.
"""

from __future__ import annotations

import io
import logging
import math
from datetime import date, timedelta

import httpx
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..models import AssetGroup, Instrument, PriceBar
from ..universe import UNIVERSE

log = logging.getLogger(__name__)

WIKI_SP500 = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
# Wikipedia 403s the default urllib agent; a descriptive UA is their stated
# requirement, not a workaround.
USER_AGENT = "finance-dashboard/0.1 (https://github.com/AadhavSivakumar/Finance)"

# yfinance batches many symbols per request, but very large batches time out
# and fail as a unit, losing everything. 80 is a pragmatic middle.
BATCH_SIZE = 80
DEFAULT_HISTORY_YEARS = 8


# --------------------------------------------------------------------------
# Instruments
# --------------------------------------------------------------------------


def fetch_sp500_constituents() -> pd.DataFrame:
    """Current S&P 500 members with GICS sectors.

    NOTE: this is the *current* membership, which introduces survivorship
    bias -- companies that dropped out are absent, so backtests over this
    universe look better than reality. Fixing it properly needs point-in-time
    constituents, which no free source provides.
    """
    resp = httpx.get(
        WIKI_SP500, headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True
    )
    resp.raise_for_status()
    table = pd.read_html(io.StringIO(resp.text))[0]
    out = table[["Symbol", "Security", "GICS Sector"]].copy()
    out.columns = ["symbol", "name", "sector"]
    # Wikipedia writes class shares as BRK.B; Yahoo expects BRK-B.
    out["symbol"] = out["symbol"].str.strip().str.replace(".", "-", regex=False)
    return out


def sync_instruments(db: Session, include_sp500: bool = True) -> dict[str, int]:
    """Upsert the context universe and (optionally) S&P 500 constituents."""
    rows: list[dict] = [
        {
            "symbol": i.symbol,
            "name": i.name,
            "asset_group": AssetGroup(i.group),
            "sector": "",
            "short_label": i.short,
            "universe": "context",
            "is_active": True,
        }
        for i in UNIVERSE
    ]
    context_symbols = {r["symbol"] for r in rows}
    sp500_added = 0

    if include_sp500:
        try:
            df = fetch_sp500_constituents()
            for r in df.itertuples(index=False):
                if r.symbol in context_symbols:
                    continue
                rows.append(
                    {
                        "symbol": r.symbol,
                        "name": str(r.name)[:200],
                        "asset_group": AssetGroup.equity,
                        "sector": str(r.sector)[:80],
                        "short_label": "",
                        "universe": "sp500",
                        "is_active": True,
                    }
                )
            sp500_added = len(rows) - len(context_symbols)
        except Exception as exc:  # noqa: BLE001
            # A Wikipedia outage must not take the whole run down; whatever is
            # already in `instruments` stays usable.
            log.warning("S&P 500 constituent fetch failed, keeping stored list: %s", exc)

    stmt = pg_insert(Instrument).values(rows)
    stmt = stmt.on_conflict_do_update(
        index_elements=[Instrument.symbol],
        set_={
            "name": stmt.excluded.name,
            "asset_group": stmt.excluded.asset_group,
            "sector": stmt.excluded.sector,
            "short_label": stmt.excluded.short_label,
            "universe": stmt.excluded.universe,
            "is_active": stmt.excluded.is_active,
        },
    )
    db.execute(stmt)
    db.commit()
    return {"context": len(context_symbols), "sp500": sp500_added, "total": len(rows)}


def active_symbols(db: Session, universe: str | None = None) -> list[str]:
    q = select(Instrument.symbol).where(Instrument.is_active.is_(True))
    if universe:
        q = q.where(Instrument.universe == universe)
    return sorted(db.scalars(q).all())


# --------------------------------------------------------------------------
# Price bars
# --------------------------------------------------------------------------


def _latest_bar_dates(db: Session, symbols: list[str]) -> dict[str, date]:
    rows = db.execute(
        select(PriceBar.symbol, func.max(PriceBar.bar_date))
        .where(PriceBar.symbol.in_(symbols))
        .group_by(PriceBar.symbol)
    ).all()
    return {s: d for s, d in rows if d is not None}


def _download(symbols: list[str], start: date, end: date) -> pd.DataFrame:
    """Batch download -> long-format OHLCV."""
    import yfinance as yf

    raw = yf.download(
        symbols,
        # yfinance treats `end` as exclusive, so add a day to include today.
        start=start.isoformat(),
        end=(end + timedelta(days=1)).isoformat(),
        interval="1d",
        # Split/dividend adjusted, so computed returns are the returns an
        # investor actually experienced rather than raw price changes.
        auto_adjust=True,
        progress=False,
        threads=True,
        group_by="ticker",
    )

    frames = []
    for sym in symbols:
        try:
            d = raw[sym] if len(symbols) > 1 else raw
        except (KeyError, TypeError):
            continue
        d = d.dropna(subset=["Close"])
        if d.empty:
            continue
        frames.append(
            pd.DataFrame(
                {
                    "symbol": sym,
                    "bar_date": pd.to_datetime(d.index).tz_localize(None).date,
                    "open": d["Open"].to_numpy(),
                    "high": d["High"].to_numpy(),
                    "low": d["Low"].to_numpy(),
                    "close": d["Close"].to_numpy(),
                    "volume": d["Volume"].to_numpy(),
                }
            )
        )
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _upsert_bars(db: Session, frame: pd.DataFrame) -> int:
    if frame.empty:
        return 0
    records = []
    for r in frame.itertuples(index=False):
        # yfinance emits NaN for the in-progress session; storing it would
        # poison every downstream calculation.
        if any(
            v is None or (isinstance(v, float) and not math.isfinite(v))
            for v in (r.open, r.high, r.low, r.close)
        ):
            continue
        records.append(
            {
                "symbol": r.symbol,
                "bar_date": r.bar_date,
                "open": float(r.open),
                "high": float(r.high),
                "low": float(r.low),
                "close": float(r.close),
                "volume": float(r.volume) if math.isfinite(float(r.volume or 0)) else 0.0,
            }
        )
    if not records:
        return 0

    written = 0
    # Chunked to keep the statement (and its parameter list) a sane size.
    for i in range(0, len(records), 5000):
        chunk = records[i : i + 5000]
        stmt = pg_insert(PriceBar).values(chunk)
        # The newest bar can be revised intraday, so update rather than ignore.
        stmt = stmt.on_conflict_do_update(
            constraint="uq_price_bars_symbol_date",
            set_={
                "open": stmt.excluded.open,
                "high": stmt.excluded.high,
                "low": stmt.excluded.low,
                "close": stmt.excluded.close,
                "volume": stmt.excluded.volume,
            },
        )
        db.execute(stmt)
        written += len(chunk)
    db.commit()
    return written


def ingest_bars(
    db: Session,
    symbols: list[str] | None = None,
    history_years: int = DEFAULT_HISTORY_YEARS,
) -> dict[str, int]:
    """Top up price_bars for `symbols`, fetching only what is missing."""
    symbols = symbols or active_symbols(db)
    if not symbols:
        return {"symbols": 0, "bars_written": 0}

    today = date.today()
    latest = _latest_bar_dates(db, symbols)
    full_start = today - timedelta(days=int(history_years * 365.25))

    # Split into "needs full history" and "needs a top-up" so a first run and a
    # daily run are the same code path.
    cold = [s for s in symbols if s not in latest]
    warm = [s for s in symbols if s in latest]

    written = 0
    for group, start in (
        (cold, full_start),
        # Re-fetch a few days of overlap: the most recent bars get revised, and
        # the upsert makes redundant rows harmless.
        (warm, min(latest.values()) - timedelta(days=5) if warm else today),
    ):
        if not group:
            continue
        if start >= today:
            continue
        for i in range(0, len(group), BATCH_SIZE):
            batch = group[i : i + BATCH_SIZE]
            try:
                frame = _download(batch, start, today)
            except Exception as exc:  # noqa: BLE001
                log.warning("download failed for %d symbols: %s", len(batch), exc)
                continue
            written += _upsert_bars(db, frame)
            log.info("ingested %d/%d symbols", min(i + BATCH_SIZE, len(group)), len(group))

    return {"symbols": len(symbols), "bars_written": written}


def load_bars(
    db: Session, symbols: list[str] | None = None, since: date | None = None
) -> pd.DataFrame:
    """Read price_bars back as the long-format frame the feature code wants."""
    q = select(
        PriceBar.symbol, PriceBar.bar_date, PriceBar.open, PriceBar.high,
        PriceBar.low, PriceBar.close, PriceBar.volume,
    )
    if symbols:
        q = q.where(PriceBar.symbol.in_(symbols))
    if since:
        q = q.where(PriceBar.bar_date >= since)

    rows = db.execute(q.order_by(PriceBar.symbol, PriceBar.bar_date)).all()
    if not rows:
        return pd.DataFrame(
            columns=["symbol", "date", "open", "high", "low", "close", "volume"]
        )

    frame = pd.DataFrame(rows, columns=["symbol", "date", "open", "high", "low", "close", "volume"])
    frame["date"] = pd.to_datetime(frame["date"])
    for c in ("open", "high", "low", "close", "volume"):
        frame[c] = frame[c].astype(float)
    return frame
