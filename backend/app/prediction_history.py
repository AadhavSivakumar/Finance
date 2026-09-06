"""Persist published predictions across stateless CI runs.

The live track record scores yesterday's picks against today's outcomes. That
needs yesterday's picks to still exist -- and the GitHub Actions build starts
from an empty database every time. So each build exports the day's predictions
to the `data` branch as one small append-only file per session, and the next
build imports every file back before scoring.

One file per session, never rewritten: history stays auditable, a bad run
cannot silently overwrite a good day, and git shows exactly what was published
when. ~30KB per day across all targets and models.

  python -m app.prediction_history export --out ../data-branch/predictions
  python -m app.prediction_history import  --dir ../data-branch/predictions
"""

from __future__ import annotations

import argparse
import json
import logging
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from .db import SessionLocal
from .models import Prediction

log = logging.getLogger(__name__)


def export_day(db, as_of: date, out_dir: Path) -> int:
    rows = db.execute(
        select(Prediction.symbol, Prediction.target, Prediction.model,
               Prediction.probability, Prediction.percentile)
        .where(Prediction.as_of == as_of)
        .order_by(Prediction.target, Prediction.model, Prediction.symbol)
    ).all()
    if not rows:
        return 0
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "as_of": as_of.isoformat(),
        "rows": [
            {"s": s, "t": t, "m": m, "p": round(float(p), 6),
             "q": round(float(q), 3) if q is not None else None}
            for s, t, m, p, q in rows
        ],
    }
    (out_dir / f"{as_of.isoformat()}.json").write_text(
        json.dumps(payload, separators=(",", ":"))
    )
    return len(rows)


def export_all(db, out_dir: Path) -> dict[str, int]:
    """Every session in the table -- used once, to bootstrap from a stateful DB."""
    days = db.scalars(select(Prediction.as_of).distinct().order_by(Prediction.as_of)).all()
    return {d.isoformat(): export_day(db, d, out_dir) for d in days}


def import_dir(db, in_dir: Path) -> dict[str, int]:
    """Upsert every per-day file. Idempotent: re-importing changes nothing."""
    if not in_dir.exists():
        return {}
    counts: dict[str, int] = {}
    for path in sorted(in_dir.glob("*.json")):
        payload = json.loads(path.read_text())
        as_of = date.fromisoformat(payload["as_of"])
        rows = [
            {"symbol": r["s"], "as_of": as_of, "target": r["t"], "model": r["m"],
             "probability": r["p"], "percentile": r["q"]}
            for r in payload["rows"]
        ]
        if not rows:
            continue
        for i in range(0, len(rows), 5000):
            stmt = pg_insert(Prediction).values(rows[i : i + 5000])
            # A stored day is the record of what was published; never overwrite.
            db.execute(stmt.on_conflict_do_nothing(constraint="uq_predictions_key"))
        counts[payload["as_of"]] = len(rows)
    db.commit()
    return counts


def main() -> int:
    logging.basicConfig(level="INFO", format="%(levelname)s %(message)s")
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    e = sub.add_parser("export"); e.add_argument("--out", required=True)
    e.add_argument("--all", action="store_true", help="every session, not just the latest")
    i = sub.add_parser("import"); i.add_argument("--dir", required=True)
    args = ap.parse_args()

    db = SessionLocal()
    try:
        if args.cmd == "export":
            out = Path(args.out)
            if args.all:
                result = export_all(db, out)
            else:
                latest = db.scalar(select(Prediction.as_of).order_by(Prediction.as_of.desc()).limit(1))
                result = {latest.isoformat(): export_day(db, latest, out)} if latest else {}
            log.info("exported %s", result)
        else:
            result = import_dir(db, Path(args.dir))
            log.info("imported %d sessions, %d rows", len(result), sum(result.values()))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
