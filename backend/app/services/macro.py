"""Macroeconomic series.

Everything here is fetched through OpenBB providers that need **no API key**
(`federal_reserve` for rates, `oecd` for CPI and unemployment). FRED's own API
needs a key and its keyless CSV endpoint is not reliably reachable, so those
were rejected in favour of sources that work on a fresh clone.

The derived 10y-2y spread is included because the curve's *shape* is the
signal, not either yield on its own: sustained inversion has preceded every
US recession in the modern record.
"""

from __future__ import annotations

import logging
from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..models import MacroObservation, MacroSeries

log = logging.getLogger(__name__)

# series_id -> (title, units, category)
SERIES_META: dict[str, tuple[str, str, str]] = {
    "UST10Y": ("10-Year Treasury Yield", "%", "rates"),
    "UST2Y": ("2-Year Treasury Yield", "%", "rates"),
    "UST3M": ("3-Month Treasury Yield", "%", "rates"),
    "T10Y2Y": ("10Y-2Y Yield Spread", "%", "rates"),
    "EFFR": ("Effective Federal Funds Rate", "%", "rates"),
    "SOFR": ("Secured Overnight Financing Rate", "%", "rates"),
    "CPI_YOY": ("CPI Inflation (year-over-year)", "%", "inflation"),
    "UNRATE": ("Unemployment Rate", "%", "labor"),
}


def _pct(value) -> float | None:
    """OpenBB returns rates as decimals (0.0469); display wants percent."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    # Anything under 1.0 is a decimal fraction; a genuine 4.69% never is.
    return round(f * 100, 6) if abs(f) < 1 else round(f, 6)


def _collect_treasuries() -> dict[str, list[tuple[date, float | None]]]:
    from openbb import obb

    out: dict[str, list[tuple[date, float | None]]] = {
        "UST10Y": [], "UST2Y": [], "UST3M": [], "T10Y2Y": []
    }
    rows = obb.fixedincome.government.treasury_rates(provider="federal_reserve").results
    for r in rows:
        d = getattr(r, "date", None)
        if d is None:
            continue
        ten = _pct(getattr(r, "year_10", None))
        two = _pct(getattr(r, "year_2", None))
        three_m = _pct(getattr(r, "month_3", None))
        out["UST10Y"].append((d, ten))
        out["UST2Y"].append((d, two))
        out["UST3M"].append((d, three_m))
        out["T10Y2Y"].append((d, round(ten - two, 6) if ten is not None and two is not None else None))
    return out


def _collect_simple(series_id: str) -> list[tuple[date, float | None]]:
    from openbb import obb

    if series_id == "EFFR":
        rows = obb.fixedincome.rate.effr(provider="federal_reserve").results
        field = "rate"
    elif series_id == "SOFR":
        rows = obb.fixedincome.rate.sofr(provider="federal_reserve").results
        field = "rate"
    elif series_id == "CPI_YOY":
        rows = obb.economy.cpi(
            country="united_states", frequency="monthly", provider="oecd"
        ).results
        field = "value"
    elif series_id == "UNRATE":
        rows = obb.economy.unemployment(country="united_states", provider="oecd").results
        field = "value"
    else:
        return []

    out = []
    for r in rows:
        d = getattr(r, "date", None)
        if d is None:
            continue
        out.append((d, _pct(getattr(r, field, None))))
    return out


def refresh(db: Session) -> dict[str, int]:
    """Fetch and upsert every macro series. Failures are per-series."""
    # Metadata first so observations always have a parent row.
    meta_rows = [
        {"series_id": sid, "title": t, "units": u, "category": c}
        for sid, (t, u, c) in SERIES_META.items()
    ]
    stmt = pg_insert(MacroSeries).values(meta_rows)
    db.execute(
        stmt.on_conflict_do_update(
            index_elements=[MacroSeries.series_id],
            set_={"title": stmt.excluded.title, "units": stmt.excluded.units,
                  "category": stmt.excluded.category},
        )
    )
    db.commit()

    collected: dict[str, list[tuple[date, float | None]]] = {}
    try:
        collected.update(_collect_treasuries())
    except Exception as exc:  # noqa: BLE001
        log.warning("treasury fetch failed: %s", exc)

    for sid in ("EFFR", "SOFR", "CPI_YOY", "UNRATE"):
        try:
            collected[sid] = _collect_simple(sid)
        except Exception as exc:  # noqa: BLE001
            log.warning("%s fetch failed: %s", sid, exc)

    written: dict[str, int] = {}
    for sid, points in collected.items():
        rows = [
            {"series_id": sid, "obs_date": d, "value": v}
            for d, v in points
            if d is not None
        ]
        if not rows:
            continue
        for i in range(0, len(rows), 5000):
            chunk = rows[i : i + 5000]
            st = pg_insert(MacroObservation).values(chunk)
            db.execute(
                st.on_conflict_do_update(
                    constraint="uq_macro_obs", set_={"value": st.excluded.value}
                )
            )
        written[sid] = len(rows)
    db.commit()
    return written


def latest(db: Session, series_id: str) -> tuple[date, float] | None:
    row = db.execute(
        select(MacroObservation.obs_date, MacroObservation.value)
        .where(MacroObservation.series_id == series_id, MacroObservation.value.isnot(None))
        .order_by(MacroObservation.obs_date.desc())
        .limit(1)
    ).first()
    return (row[0], row[1]) if row else None
