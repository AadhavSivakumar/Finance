"""Background worker: the "constantly calculating" half of the dashboard.

Runs two cycles at different cadences, because they cost wildly different
amounts:

* **refresh** (default 15 min) -- top up bars, recompute features, snapshots,
  signals, correlations and today's predictions using the *stored* models.
  Cheap: incremental ingest is a handful of requests and the compute is
  vectorised.
* **training** (default daily) -- refit models and re-run the full
  walk-forward evaluation. Expensive, and pointless to do more often: the
  models are fitted on 8 years of daily bars, so an extra afternoon changes
  nothing.

Why a separate container rather than a thread inside the API: a long compute
in the API process blocks request handlers and makes healthchecks flap, and
the two have completely different scaling and restart characteristics. Sharing
one image and differing only by command is the standard Compose idiom.

Deliberately a plain loop rather than APScheduler/Celery -- one dependency
fewer, and the control flow is visible.
"""

from __future__ import annotations

import logging
import os
import signal
import time
import traceback
from datetime import date, datetime, timezone

import pandas as pd

from .config import get_settings
from .db import SessionLocal
from .models import ComputeRun, RunStatus
from .services import analytics, ingest, macro, modeling
from .services import features as F
from .services import labels as L

log = logging.getLogger("worker")
settings = get_settings()

REFRESH_SECONDS = int(os.getenv("WORKER_REFRESH_SECONDS", "900"))
TRAINING_SECONDS = int(os.getenv("WORKER_TRAINING_SECONDS", "86400"))
HISTORY_YEARS = int(os.getenv("WORKER_HISTORY_YEARS", "8"))
INCLUDE_SP500 = os.getenv("WORKER_INCLUDE_SP500", "1") == "1"

_shutdown = False


def _handle_signal(signum, _frame):
    """SIGTERM from `docker stop` must end the loop cleanly rather than being
    killed 10 seconds later mid-write."""
    global _shutdown
    log.info("received signal %s, finishing current cycle", signum)
    _shutdown = True


class run_tracker:
    """Context manager recording each cycle into compute_runs.

    Makes "is this data stale, or did the worker die?" answerable in the UI
    instead of a guess.
    """

    def __init__(self, db, kind: str):
        self.db, self.kind, self.row = db, kind, None

    def __enter__(self) -> ComputeRun:
        self.row = ComputeRun(kind=self.kind, status=RunStatus.running)
        self.db.add(self.row)
        self.db.commit()
        self.started = time.monotonic()
        return self.row

    def __exit__(self, exc_type, exc, tb):
        self.row.finished_at = datetime.now(timezone.utc)
        self.row.duration_seconds = round(time.monotonic() - self.started, 2)
        if exc_type is None:
            self.row.status = RunStatus.success
        else:
            self.row.status = RunStatus.failed
            self.row.error = "".join(traceback.format_exception(exc_type, exc, tb))[-4000:]
            log.exception("%s cycle failed", self.kind)
        self.db.commit()
        return True  # a failed cycle must not kill the worker


def build_frame(db) -> tuple[pd.DataFrame, pd.DataFrame, date | None]:
    """Load bars and derive features+labels. Shared by both cycles."""
    bars = ingest.load_bars(db)
    if bars.empty:
        return bars, pd.DataFrame(), None
    feats = L.add_labels(F.build_features(bars), bars)
    as_of = bars["date"].max().date()
    return bars, feats, as_of


def refresh_cycle(db) -> dict:
    with run_tracker(db, "refresh") as run:
        stats = ingest.ingest_bars(db, history_years=HISTORY_YEARS)
        bars, feats, as_of = build_frame(db)
        if as_of is None:
            run.detail = {"error": "no bars"}
            return run.detail

        detail = {
            **stats,
            "as_of": as_of.isoformat(),
            "snapshots": analytics.persist_snapshots(db, feats, as_of),
            "correlations": analytics.persist_correlations(db, bars, as_of),
            "signals": analytics.persist_signals(
                db, analytics.detect_signals(feats, as_of), as_of
            ),
            "predictions": modeling.predict_all(db, feats, as_of),
        }
        run.detail = detail
        log.info("refresh complete: %s", detail)
        return detail


def training_cycle(db) -> dict:
    with run_tracker(db, "training") as run:
        ingest.sync_instruments(db, include_sp500=INCLUDE_SP500)
        _, feats, as_of = build_frame(db)
        if as_of is None:
            run.detail = {"error": "no bars"}
            return run.detail
        detail = {
            "as_of": as_of.isoformat(),
            "models": modeling.train_all(db, feats),
            "macro": macro.refresh(db),
        }
        run.detail = detail
        log.info("training complete: %s", detail)
        return detail


def main() -> None:
    logging.basicConfig(
        level=settings.log_level,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    log.info(
        "worker starting (refresh=%ss, training=%ss, sp500=%s)",
        REFRESH_SECONDS, TRAINING_SECONDS, INCLUDE_SP500,
    )

    db = SessionLocal()
    last_training = 0.0

    # Train on boot if no model has ever been stored, so a fresh stack becomes
    # useful without waiting a full day.
    if modeling.needs_initial_training(db):
        log.info("no trained models found — running initial training")
        training_cycle(db)
        last_training = time.monotonic()

    while not _shutdown:
        cycle_start = time.monotonic()
        refresh_cycle(db)

        if time.monotonic() - last_training >= TRAINING_SECONDS:
            training_cycle(db)
            last_training = time.monotonic()

        elapsed = time.monotonic() - cycle_start
        sleep_for = max(5.0, REFRESH_SECONDS - elapsed)
        log.info("cycle took %.0fs, sleeping %.0fs", elapsed, sleep_for)

        # Sleep in slices so SIGTERM is noticed promptly instead of after a
        # full 15-minute nap.
        waited = 0.0
        while waited < sleep_for and not _shutdown:
            time.sleep(min(2.0, sleep_for - waited))
            waited += 2.0

    db.close()
    log.info("worker stopped cleanly")


if __name__ == "__main__":
    main()
