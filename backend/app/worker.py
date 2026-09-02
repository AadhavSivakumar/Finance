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
from .services import analytics, ingest, macro, modeling, news
from .services import features as F
from .universe import BENCHMARK
from .services import labels as L

log = logging.getLogger("worker")
settings = get_settings()

REFRESH_SECONDS = int(os.getenv("WORKER_REFRESH_SECONDS", "900"))
TRAINING_SECONDS = int(os.getenv("WORKER_TRAINING_SECONDS", "86400"))
# Headlines move far faster than daily bars, so they get their own, much
# tighter cadence rather than riding along with the 15-minute market refresh.
NEWS_SECONDS = int(os.getenv("WORKER_NEWS_SECONDS", "300"))
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

    # as_of is the last date the BENCHMARK traded, not the last date any
    # instrument did. Crypto trades weekends, so the global max is routinely a
    # Saturday on which only BTC/ETH/SOL have bars -- computing a market-wide
    # snapshot there yields breadth and advancer figures drawn from three
    # instruments.
    bench = bars[bars["symbol"] == BENCHMARK]
    as_of = (bench["date"].max() if not bench.empty else bars["date"].max()).date()
    return bars, feats, as_of


def news_cycle(db) -> dict:
    """Headlines only -- deliberately cheap so it can run every 5 minutes.

    Four RSS fetches and an upsert; no bars, no features, no models.
    """
    with run_tracker(db, "news") as run:
        run.detail = news.refresh(db)
        return run.detail


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

        # Ingest before building the frame. On a fresh database there are no
        # bars yet, and training would otherwise bail with "no bars" -- which
        # is exactly what happened on the first CI run, where the database
        # starts empty every time. Locally this was masked because bars had
        # already been ingested by an earlier refresh.
        stats = ingest.ingest_bars(db, history_years=HISTORY_YEARS)

        _, feats, as_of = build_frame(db)
        if as_of is None:
            run.detail = {"error": "no bars"}
            return run.detail
        detail = {
            **stats,
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
    news_cycle(db)  # populate immediately; do not show an empty feed for 5 min

    # Train on boot if no model has ever been stored, so a fresh stack becomes
    # useful without waiting a full day.
    if modeling.needs_initial_training(db):
        log.info("no trained models found — running initial training")
        training_cycle(db)
        last_training = time.monotonic()

    last_refresh = 0.0
    last_news = 0.0

    # Three independent timers rather than one loop period, because the three
    # jobs have wildly different costs: news is seconds, refresh is ~30s, and
    # training is minutes. Ticking every few seconds and checking each timer
    # keeps the fast job fast without dragging the slow ones along.
    while not _shutdown:
        now = time.monotonic()

        if now - last_news >= NEWS_SECONDS:
            news_cycle(db)
            last_news = time.monotonic()

        if now - last_refresh >= REFRESH_SECONDS:
            started = time.monotonic()
            refresh_cycle(db)
            last_refresh = time.monotonic()
            log.info("refresh took %.0fs", last_refresh - started)

        if now - last_training >= TRAINING_SECONDS:
            training_cycle(db)
            last_training = time.monotonic()

        # Short tick so SIGTERM is noticed promptly and the 5-minute news
        # cadence is not quantised by a 15-minute sleep.
        waited = 0.0
        while waited < 5.0 and not _shutdown:
            time.sleep(1.0)
            waited += 1.0

    db.close()
    log.info("worker stopped cleanly")


if __name__ == "__main__":
    main()
