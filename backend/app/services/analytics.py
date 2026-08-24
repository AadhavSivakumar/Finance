"""Turn raw bars into the things the dashboard displays.

Four outputs:

* **snapshots**  -- one row per symbol for the latest date, holding the metrics
  the tables sort by.
* **signals**    -- discrete, explainable events ("50d crossed above 200d").
  A probability tells you *that* something is likely; a signal tells you *why*,
  which is what a human can actually check.
* **correlations** -- the pairwise matrix for the context universe.
* **regime**     -- the one-glance read on market state.

Only the latest date is persisted for snapshots and signals. Storing every
date for 529 symbols over 8 years would be ~1M rows to serve a table that only
ever shows today.
"""

from __future__ import annotations

import logging
from datetime import date

import numpy as np
import pandas as pd
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..models import CorrelationSnapshot, Instrument, Signal, Snapshot
from ..universe import BY_SYMBOL, RANKABLE_GROUPS, symbols_in
from . import indicators as I

log = logging.getLogger(__name__)

CORRELATION_WINDOW = 90

# Columns promoted to typed snapshot fields; everything else goes to `extras`.
SNAPSHOT_FIELDS = [
    "close", "ret_1d", "ret_5d", "ret_21d", "ret_63d", "ret_252d",
    "rsi_14", "vol_20d", "vol_ratio_10_60", "atr_pct",
    "pct_from_52w_high", "drawdown_pct", "volume_z", "rel_strength_21d",
    "px_over_sma200",
]

EXTRA_FIELDS = [
    "ret_10d", "ret_126d", "rsi_5", "macd_hist_norm", "bb_percent_b",
    "bb_bandwidth", "vol_10d", "vol_60d", "sma50_over_sma200",
    "sma20_over_sma50", "px_over_sma20", "px_over_sma50",
    "pct_from_52w_low", "volume_ratio_5_20", "close_in_range", "gap_pct",
    "rel_strength_5d",
]


def _clean(value) -> float | None:
    """NaN/inf -> None. Postgres accepts NaN in a float column and then every
    aggregate over it silently becomes NaN."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if np.isfinite(f) else None


# --------------------------------------------------------------------------
# Snapshots
# --------------------------------------------------------------------------


def persist_snapshots(db: Session, feats: pd.DataFrame, as_of: date) -> int:
    """Upsert one snapshot row per symbol for `as_of`."""
    latest = feats[feats.index.get_level_values("date").date == as_of]
    if latest.empty:
        return 0

    rows = []
    for (symbol, _), r in latest.iterrows():
        record = {"symbol": symbol, "as_of": as_of}
        for f in SNAPSHOT_FIELDS:
            record[f] = _clean(r.get(f))
        record["extras"] = {
            f: _clean(r.get(f)) for f in EXTRA_FIELDS if f in latest.columns
        }
        rows.append(record)

    stmt = pg_insert(Snapshot).values(rows)
    stmt = stmt.on_conflict_do_update(
        constraint="uq_snapshots_symbol_date",
        set_={f: stmt.excluded[f] for f in SNAPSHOT_FIELDS + ["extras"]},
    )
    db.execute(stmt)
    db.commit()
    return len(rows)


# --------------------------------------------------------------------------
# Signals
# --------------------------------------------------------------------------


def _crossed_above(series: pd.Series, threshold: float = 0.0) -> bool:
    """True when the series moved from <=threshold to >threshold on the last bar."""
    s = series.dropna()
    if len(s) < 2:
        return False
    return bool(s.iloc[-2] <= threshold < s.iloc[-1])


def detect_signals(feats: pd.DataFrame, as_of: date) -> list[dict]:
    """Explainable events on the latest bar.

    Thresholds are conventional (RSI 70/30, 3-sigma volume). They are not
    tuned, on purpose: a tuned threshold on this much data is an overfit
    threshold, and these exist to explain rather than to predict.
    """
    out: list[dict] = []
    dates = feats.index.get_level_values("date").date

    for symbol, g in feats.groupby(level="symbol"):
        g = g.sort_index()
        if g.empty or g.index.get_level_values("date").date[-1] != as_of:
            continue
        last = g.iloc[-1]

        rsi = _clean(last.get("rsi_14"))
        if rsi is not None:
            if rsi >= 70:
                out.append(dict(symbol=symbol, as_of=as_of, kind="rsi_overbought",
                                direction="bearish", strength=rsi,
                                detail=f"RSI(14) at {rsi:.0f} — stretched to the upside"))
            elif rsi <= 30:
                out.append(dict(symbol=symbol, as_of=as_of, kind="rsi_oversold",
                                direction="bullish", strength=rsi,
                                detail=f"RSI(14) at {rsi:.0f} — stretched to the downside"))

        # Golden/death cross on the 50/200 spread changing sign.
        spread = g["sma50_over_sma200"] if "sma50_over_sma200" in g else pd.Series(dtype=float)
        if _crossed_above(spread):
            out.append(dict(symbol=symbol, as_of=as_of, kind="golden_cross",
                            direction="bullish", strength=_clean(spread.iloc[-1]),
                            detail="50-day moving average crossed above the 200-day"))
        elif _crossed_above(-spread):
            out.append(dict(symbol=symbol, as_of=as_of, kind="death_cross",
                            direction="bearish", strength=_clean(spread.iloc[-1]),
                            detail="50-day moving average crossed below the 200-day"))

        vz = _clean(last.get("volume_z"))
        if vz is not None and vz >= 3:
            out.append(dict(symbol=symbol, as_of=as_of, kind="volume_spike",
                            direction="neutral", strength=vz,
                            detail=f"Volume {vz:.1f} standard deviations above its 20-day norm"))

        vr = _clean(last.get("vol_ratio_10_60"))
        if vr is not None and vr >= 1.6:
            out.append(dict(symbol=symbol, as_of=as_of, kind="volatility_expansion",
                            direction="neutral", strength=vr,
                            detail=f"10-day volatility {vr:.1f}x its 60-day level"))

        # Bollinger squeeze: bandwidth in the bottom decile of its own year.
        if "bb_bandwidth" in g:
            bw = g["bb_bandwidth"].dropna().tail(252)
            if len(bw) > 60:
                cur = bw.iloc[-1]
                if cur <= bw.quantile(0.10):
                    out.append(dict(symbol=symbol, as_of=as_of, kind="volatility_squeeze",
                                    direction="neutral", strength=_clean(cur),
                                    detail="Bollinger bandwidth in the bottom decile of the past year — compression often precedes expansion"))

        fh = _clean(last.get("pct_from_52w_high"))
        if fh is not None and fh >= -2:
            out.append(dict(symbol=symbol, as_of=as_of, kind="near_52w_high",
                            direction="bullish", strength=fh,
                            detail=f"Within {abs(fh):.1f}% of its 52-week high"))
        fl = _clean(last.get("pct_from_52w_low"))
        if fl is not None and fl <= 2:
            out.append(dict(symbol=symbol, as_of=as_of, kind="near_52w_low",
                            direction="bearish", strength=fl,
                            detail=f"Within {abs(fl):.1f}% of its 52-week low"))

    return out


def persist_signals(db: Session, signals: list[dict], as_of: date) -> int:
    # Replace the day's signals wholesale: a rerun must not leave stale rows
    # from an earlier partial computation.
    db.execute(delete(Signal).where(Signal.as_of == as_of))
    if signals:
        db.execute(pg_insert(Signal).values(signals).on_conflict_do_nothing(
            constraint="uq_signals_key"))
    db.commit()
    return len(signals)


# --------------------------------------------------------------------------
# Correlations
# --------------------------------------------------------------------------


def persist_correlations(
    db: Session, bars: pd.DataFrame, as_of: date, window: int = CORRELATION_WINDOW
) -> int:
    """Correlation matrix over the context universe only.

    529x529 would be 140k cells -- unreadable as a heatmap and pointless to
    store. The ~25 cross-asset instruments are what the question "what is
    actually diversifying right now" is about.
    """
    symbols = [s for s in symbols_in(*RANKABLE_GROUPS, "volatility")]
    wide = (
        bars[bars["symbol"].isin(symbols)]
        .pivot_table(index="date", columns="symbol", values="close")
        .sort_index()
    )
    if wide.shape[1] < 3:
        return 0

    matrix = I.correlation_matrix(wide, window=window)
    cols = list(matrix.columns)
    values = [[_clean(v) for v in row] for row in matrix.to_numpy()]

    stmt = pg_insert(CorrelationSnapshot).values(
        as_of=as_of, window=window, symbols=cols, matrix=values
    )
    stmt = stmt.on_conflict_do_update(
        constraint="uq_correlation_key",
        set_={"symbols": stmt.excluded.symbols, "matrix": stmt.excluded.matrix},
    )
    db.execute(stmt)
    db.commit()
    return len(cols)


def average_correlation(matrix: list[list[float | None]]) -> float | None:
    """Mean off-diagonal correlation -- a single number for 'how much is
    everything moving together', which is what rises in a crisis."""
    vals = [
        v
        for i, row in enumerate(matrix)
        for j, v in enumerate(row)
        if i != j and v is not None
    ]
    return float(np.mean(vals)) if vals else None


# --------------------------------------------------------------------------
# Regime
# --------------------------------------------------------------------------


def compute_regime(db: Session, feats: pd.DataFrame, as_of: date) -> dict:
    """Breadth, trend and volatility, condensed to one read."""
    latest = feats[feats.index.get_level_values("date").date == as_of]
    if latest.empty:
        return {}

    above_200 = latest["px_over_sma200"].dropna()
    breadth = float((above_200 > 0).mean() * 100) if len(above_200) else 0.0

    day_ret = latest["ret_1d"].dropna()
    advancers = float((day_ret > 0).mean() * 100) if len(day_ret) else 0.0

    spy = latest.xs("SPY", level="symbol", drop_level=False)
    spy_trend = _clean(spy["px_over_sma200"].iloc[0]) if len(spy) else None

    # vix_level is a market-context column broadcast onto every row, so any
    # single symbol's series carries the full VIX history.
    vix_level = vix_pct = None
    if "vix_level" in feats.columns:
        one = feats.index.get_level_values("symbol")[0]
        vix_hist = feats.xs(one, level="symbol")["vix_level"].dropna()
        if len(vix_hist):
            vix_level = _clean(vix_hist.iloc[-1])
            year = vix_hist.tail(252)
            # A percentile is far more useful than the raw level: VIX 20 means
            # something different in 2017 than in 2020.
            if len(year) > 30 and vix_level is not None:
                vix_pct = float((year < vix_level).mean() * 100)

    corr_row = db.scalars(
        select(CorrelationSnapshot)
        .where(CorrelationSnapshot.as_of <= as_of)
        .order_by(CorrelationSnapshot.as_of.desc())
        .limit(1)
    ).first()
    avg_corr = average_correlation(corr_row.matrix) if corr_row else None

    notes: list[str] = []
    score = 0
    if spy_trend is not None:
        if spy_trend > 0:
            score += 1
            notes.append("S&P 500 is above its 200-day average")
        else:
            score -= 1
            notes.append("S&P 500 is below its 200-day average")
    if breadth >= 60:
        score += 1
        notes.append(f"Broad participation — {breadth:.0f}% of the universe above its 200-day")
    elif breadth <= 40:
        score -= 1
        notes.append(f"Narrow market — only {breadth:.0f}% above their 200-day")
    if vix_pct is not None:
        if vix_pct >= 80:
            score -= 1
            notes.append(f"VIX in the {vix_pct:.0f}th percentile of the past year")
        elif vix_pct <= 20:
            score += 1
            notes.append(f"VIX subdued — {vix_pct:.0f}th percentile of the past year")
    if avg_corr is not None and avg_corr >= 0.6:
        notes.append(f"Average cross-asset correlation {avg_corr:.2f} — diversification is thin")

    trend = "risk-on" if score >= 2 else "risk-off" if score <= -2 else "mixed"

    return {
        "as_of": as_of,
        "trend": trend,
        "breadth_pct": round(breadth, 2),
        "advancers_pct": round(advancers, 2),
        "spy_px_over_sma200": spy_trend,
        "vix_level": vix_level,
        "vix_percentile_1y": round(vix_pct, 2) if vix_pct is not None else None,
        "avg_correlation": round(avg_corr, 4) if avg_corr is not None else None,
        "notes": notes,
    }
