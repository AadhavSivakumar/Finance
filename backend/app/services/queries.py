"""Read-side queries.

Deliberately shared by the HTTP API and the static exporter. The GitHub Pages
build serves precomputed JSON while the local stack serves the same data over
HTTP; routing both through one module is what stops the two from drifting into
subtly different numbers.

Everything returns plain dicts/lists ready for JSON, so the exporter does not
need a serialisation layer of its own.
"""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from ..models import (
    ComputeRun,
    CorrelationSnapshot,
    Instrument,
    MacroObservation,
    MacroSeries,
    ModelRun,
    Prediction,
    PriceBar,
    Signal,
    Snapshot,
)
from ..universe import BY_SYMBOL
from . import analytics

# Long daily series (EFFR has ~2600 points) would dominate the payload, so
# each series is thinned to at most this many points for display.
MAX_MACRO_POINTS = 400


def _f(v) -> float | None:
    return None if v is None else round(float(v), 6)


# The latest date overall is not the latest *market session*: crypto trades
# 24/7, so weekends and holidays produce dates containing only BTC/ETH/SOL.
# Computing breadth from three instruments yields "100% above their 200-day",
# which is nonsense. Anchoring to the benchmark gives the last real session.
BENCHMARK_SYMBOL = "SPY"


def latest_as_of(db: Session) -> date | None:
    """Most recent date on which the benchmark has a snapshot."""
    anchored = db.scalar(
        select(func.max(Snapshot.as_of)).where(Snapshot.symbol == BENCHMARK_SYMBOL)
    )
    # Fall back to the global max only if the benchmark is missing entirely,
    # so a fresh database still renders something.
    return anchored or db.scalar(select(func.max(Snapshot.as_of)))


# --------------------------------------------------------------------------
# Instruments + movers
# --------------------------------------------------------------------------


def _instrument_map(db: Session) -> dict[str, Instrument]:
    return {i.symbol: i for i in db.scalars(select(Instrument))}


def movers(db: Session, as_of: date | None = None) -> list[dict]:
    """Every symbol's latest metrics, joined to display metadata."""
    as_of = as_of or latest_as_of(db)
    if as_of is None:
        return []
    instruments = _instrument_map(db)
    rows = db.scalars(select(Snapshot).where(Snapshot.as_of == as_of)).all()

    out = []
    for s in rows:
        inst = instruments.get(s.symbol)
        out.append(
            {
                "symbol": s.symbol,
                "name": inst.name if inst else s.symbol,
                "short_label": (inst.short_label if inst else "") or s.symbol,
                "group": inst.asset_group.value if inst else "equity",
                "sector": inst.sector if inst else "",
                "universe": inst.universe if inst else "sp500",
                "close": _f(s.close),
                "ret_1d": _f(s.ret_1d),
                "ret_5d": _f(s.ret_5d),
                "ret_21d": _f(s.ret_21d),
                "ret_63d": _f(s.ret_63d),
                "ret_252d": _f(s.ret_252d),
                "rsi_14": _f(s.rsi_14),
                "vol_20d": _f(s.vol_20d),
                "vol_ratio_10_60": _f(s.vol_ratio_10_60),
                "atr_pct": _f(s.atr_pct),
                "pct_from_52w_high": _f(s.pct_from_52w_high),
                "drawdown_pct": _f(s.drawdown_pct),
                "volume_z": _f(s.volume_z),
                "rel_strength_21d": _f(s.rel_strength_21d),
                "px_over_sma200": _f(s.px_over_sma200),
            }
        )
    out.sort(key=lambda r: (r["ret_1d"] is None, -(r["ret_1d"] or 0)))
    return out


def sector_rotation(db: Session, as_of: date | None = None) -> list[dict]:
    """The 11 sector SPDRs across several lookbacks -- the rotation view."""
    rows = [m for m in movers(db, as_of) if m["group"] == "sector"]
    rows.sort(key=lambda r: (r["ret_21d"] is None, -(r["ret_21d"] or 0)))
    return rows


# --------------------------------------------------------------------------
# Regime
# --------------------------------------------------------------------------


def regime(db: Session, as_of: date | None = None) -> dict:
    """Rebuilt from stored snapshots rather than recomputed from bars.

    The worker already did this arithmetic; recomputing here would mean
    loading a million bars to serve one card.
    """
    as_of = as_of or latest_as_of(db)
    if as_of is None:
        return {}

    rows = db.scalars(select(Snapshot).where(Snapshot.as_of == as_of)).all()
    if not rows:
        return {}

    above = [r.px_over_sma200 for r in rows if r.px_over_sma200 is not None]
    breadth = (sum(1 for v in above if v > 0) / len(above) * 100) if above else 0.0
    day = [r.ret_1d for r in rows if r.ret_1d is not None]
    advancers = (sum(1 for v in day if v > 0) / len(day) * 100) if day else 0.0

    by_symbol = {r.symbol: r for r in rows}
    spy = by_symbol.get("SPY")
    spy_trend = _f(spy.px_over_sma200) if spy else None

    vix = by_symbol.get("^VIX")
    vix_level = _f(vix.close) if vix else None
    vix_pct = None
    if vix_level is not None:
        year = db.scalars(
            select(Snapshot.close)
            .where(Snapshot.symbol == "^VIX", Snapshot.as_of <= as_of)
            .order_by(Snapshot.as_of.desc())
            .limit(252)
        ).all()
        # Snapshots only exist from the day the worker started, so fall back to
        # the price_bars history, which goes back years.
        if len(year) < 60:
            year = db.scalars(
                select(PriceBar.close)
                .where(PriceBar.symbol == "^VIX", PriceBar.bar_date <= as_of)
                .order_by(PriceBar.bar_date.desc())
                .limit(252)
            ).all()
        vals = [float(v) for v in year if v is not None]
        if len(vals) >= 60:
            vix_pct = round(sum(1 for v in vals if v < vix_level) / len(vals) * 100, 2)

    corr = db.scalars(
        select(CorrelationSnapshot)
        .where(CorrelationSnapshot.as_of <= as_of)
        .order_by(CorrelationSnapshot.as_of.desc())
        .limit(1)
    ).first()
    avg_corr = analytics.average_correlation(corr.matrix) if corr else None

    notes: list[str] = []
    score = 0
    if spy_trend is not None:
        score += 1 if spy_trend > 0 else -1
        notes.append(
            "S&P 500 is above its 200-day average"
            if spy_trend > 0
            else "S&P 500 is below its 200-day average"
        )
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

    return {
        "as_of": as_of.isoformat(),
        "trend": "risk-on" if score >= 2 else "risk-off" if score <= -2 else "mixed",
        "breadth_pct": round(breadth, 2),
        "advancers_pct": round(advancers, 2),
        "spy_px_over_sma200": spy_trend,
        "vix_level": vix_level,
        "vix_percentile_1y": vix_pct,
        "avg_correlation": round(avg_corr, 4) if avg_corr is not None else None,
        "notes": notes,
    }


# --------------------------------------------------------------------------
# Signals / predictions / models
# --------------------------------------------------------------------------


def signals(db: Session, days: int = 3, limit: int = 400) -> list[dict]:
    as_of = latest_as_of(db)
    if as_of is None:
        return []
    since = as_of - timedelta(days=days)
    instruments = _instrument_map(db)
    rows = db.scalars(
        select(Signal)
        .where(Signal.as_of >= since)
        .order_by(Signal.as_of.desc(), desc(Signal.strength))
        .limit(limit)
    ).all()
    return [
        {
            "symbol": s.symbol,
            "name": instruments[s.symbol].name if s.symbol in instruments else s.symbol,
            "as_of": s.as_of.isoformat(),
            "kind": s.kind,
            "direction": s.direction,
            "strength": _f(s.strength),
            "detail": s.detail,
        }
        for s in rows
    ]


def model_runs(db: Session) -> list[dict]:
    """Every model's latest evaluation -- including the ones that failed.

    Exported deliberately: the UI shows "evaluated, no edge" for the direction
    model rather than hiding it, so the absence of a forecast is visible
    instead of looking like a missing feature.
    """
    subq = (
        select(ModelRun.target, ModelRun.model, func.max(ModelRun.trained_at).label("t"))
        .group_by(ModelRun.target, ModelRun.model)
        .subquery()
    )
    rows = db.scalars(
        select(ModelRun)
        .join(
            subq,
            (ModelRun.target == subq.c.target)
            & (ModelRun.model == subq.c.model)
            & (ModelRun.trained_at == subq.c.t),
        )
        .order_by(ModelRun.target, ModelRun.model)
    ).all()
    return [
        {
            "target": r.target,
            "model": r.model,
            "trained_at": r.trained_at.isoformat() if r.trained_at else None,
            "n_train": r.n_train,
            "n_features": r.n_features,
            "train_start": r.train_start.isoformat() if r.train_start else None,
            "train_end": r.train_end.isoformat() if r.train_end else None,
            "roc_auc": _f(r.roc_auc),
            "base_rate": _f(r.base_rate),
            "accuracy": _f(r.accuracy),
            "baseline_accuracy": _f(r.baseline_accuracy),
            "edge_vs_baseline": _f(r.edge_vs_baseline),
            "top_decile_precision": _f(r.top_decile_precision),
            "lift": _f(r.lift),
            "is_active": bool(r.is_active),
            "horizon_days": (r.metrics or {}).get("horizon_days"),
            "folds": (r.metrics or {}).get("folds"),
        }
        for r in rows
    ]


def predictions(db: Session, target: str = "spike_2atr", limit: int = 40) -> list[dict]:
    as_of = db.scalar(select(func.max(Prediction.as_of)))
    if as_of is None:
        return []
    active = {(m["target"], m["model"]): m for m in model_runs(db) if m["is_active"]}
    if not active:
        return []
    # Prefer the strongest active model for this target.
    candidates = [k for k in active if k[0] == target]
    if not candidates:
        return []
    best = max(candidates, key=lambda k: active[k]["roc_auc"] or 0)
    meta = active[best]

    instruments = _instrument_map(db)
    rows = db.scalars(
        select(Prediction)
        .where(
            Prediction.as_of == as_of,
            Prediction.target == best[0],
            Prediction.model == best[1],
        )
        .order_by(Prediction.probability.desc())
        .limit(limit)
    ).all()
    return [
        {
            "symbol": p.symbol,
            "name": instruments[p.symbol].name if p.symbol in instruments else p.symbol,
            "sector": instruments[p.symbol].sector if p.symbol in instruments else "",
            "as_of": p.as_of.isoformat(),
            "target": p.target,
            "model": p.model,
            "probability": _f(p.probability),
            "percentile": _f(p.percentile),
            "model_roc_auc": meta["roc_auc"],
            "model_lift": meta["lift"],
            "model_base_rate": meta["base_rate"],
        }
        for p in rows
    ]


# --------------------------------------------------------------------------
# Correlations / macro / freshness
# --------------------------------------------------------------------------


def correlations(db: Session) -> dict:
    row = db.scalars(
        select(CorrelationSnapshot).order_by(CorrelationSnapshot.as_of.desc()).limit(1)
    ).first()
    if not row:
        return {}
    labels = [
        (BY_SYMBOL[s].display if s in BY_SYMBOL else s) for s in row.symbols
    ]
    return {
        "as_of": row.as_of.isoformat(),
        "window": row.window,
        "symbols": row.symbols,
        "labels": labels,
        "matrix": [[_f(v) for v in r] for r in row.matrix],
    }


def macro(db: Session) -> list[dict]:
    series = db.scalars(select(MacroSeries).order_by(MacroSeries.category, MacroSeries.series_id)).all()
    out = []
    for s in series:
        rows = db.execute(
            select(MacroObservation.obs_date, MacroObservation.value)
            .where(MacroObservation.series_id == s.series_id, MacroObservation.value.isnot(None))
            .order_by(MacroObservation.obs_date)
        ).all()
        if not rows:
            continue
        # Thin evenly rather than truncating, so the chart keeps its full span.
        step = max(1, len(rows) // MAX_MACRO_POINTS)
        thinned = rows[::step]
        if thinned[-1] != rows[-1]:
            thinned.append(rows[-1])  # always keep the newest observation

        latest_date, latest_value = rows[-1]
        year_ago = latest_date - timedelta(days=365)
        prior = next((v for d, v in reversed(rows) if d <= year_ago), None)

        out.append(
            {
                "series_id": s.series_id,
                "title": s.title,
                "units": s.units,
                "category": s.category,
                "latest_value": _f(latest_value),
                "latest_date": latest_date.isoformat(),
                "change_1y": _f(latest_value - prior) if prior is not None else None,
                "points": [{"date": d.isoformat(), "value": _f(v)} for d, v in thinned],
            }
        )
    return out


def history(db: Session, symbol: str, days: int = 400) -> list[dict]:
    rows = db.execute(
        select(PriceBar.bar_date, PriceBar.close)
        .where(PriceBar.symbol == symbol)
        .order_by(PriceBar.bar_date.desc())
        .limit(days)
    ).all()
    return [{"date": d.isoformat(), "close": float(c)} for d, c in reversed(rows)]


def freshness(db: Session) -> dict:
    runs = db.scalars(select(ComputeRun).order_by(ComputeRun.started_at.desc()).limit(20)).all()
    last_by_kind: dict[str, dict] = {}
    for r in runs:
        if r.kind in last_by_kind:
            continue
        last_by_kind[r.kind] = {
            "kind": r.kind,
            "status": r.status.value if hasattr(r.status, "value") else str(r.status),
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "finished_at": r.finished_at.isoformat() if r.finished_at else None,
            "duration_seconds": _f(r.duration_seconds),
            "detail": r.detail or {},
            "error": (r.error or "")[:500],
        }
    as_of = latest_as_of(db)
    return {
        "as_of": as_of.isoformat() if as_of else None,
        "symbols": db.scalar(select(func.count()).select_from(Instrument)) or 0,
        "bars": db.scalar(select(func.count()).select_from(PriceBar)) or 0,
        "runs": list(last_by_kind.values()),
    }
