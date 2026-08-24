"""Training, persistence and scoring of the prediction models.

Split deliberately from ``forecasting.py``: that module is pure math and knows
nothing about the database, which is what keeps it testable. This one is the
glue -- it owns the database rows, the fitted artefacts on disk, and the rule
about which models are allowed to be shown.

**The honesty gate.** A model is marked ``is_active`` only if its walk-forward
evaluation shows a positive edge over the naive baseline AND an AUC
meaningfully above chance. Everything is stored either way, so the UI can show
"evaluated, no edge found" instead of quietly presenting a coin flip as a
forecast. On real data the 5-day direction model does not pass this gate, and
that is the correct outcome rather than a bug to tune away.
"""

from __future__ import annotations

import logging
from datetime import date
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from ..config import get_settings
from ..models import ModelRun, Prediction
from . import features as F
from . import forecasting as FC
from . import labels as L

log = logging.getLogger(__name__)
settings = get_settings()

TARGETS = {
    # target -> label horizon in trading days
    "spike_2atr": 1,
    "up_5d": 5,
}
LABEL_COL = {"spike_2atr": "label_spike_2atr", "up_5d": "label_up_5d"}

# Gate thresholds. Modest on purpose: real edge in this domain is small, and
# demanding a lot would reject everything, while demanding nothing would
# publish noise.
MIN_AUC = 0.55
MIN_LIFT = 1.20
MIN_EDGE_PP = 0.0

# Accuracy-based edge is only a meaningful test when the classes are somewhat
# balanced. For a 0.85%-base-rate event, "always predict no" scores 99.15% and
# NOTHING can beat it on accuracy -- a model with AUC 0.70 and 3.4x lift still
# shows a negative edge. Applying the accuracy gate there would reject every
# rare-event model by construction, so it is applied only inside this band.
BALANCED_BAND = (20.0, 80.0)


def _passes_gate(roc_auc: float, lift: float, edge_pp: float, base_rate: float) -> bool:
    """Is this model good enough to show predictions from?

    Ranking quality (AUC) and lift are the universal criteria; the accuracy
    edge is an extra hurdle only for balanced targets.
    """
    if not (np.isfinite(roc_auc) and roc_auc >= MIN_AUC):
        return False
    if not (np.isfinite(lift) and lift >= MIN_LIFT):
        return False
    if BALANCED_BAND[0] <= base_rate <= BALANCED_BAND[1]:
        return edge_pp > MIN_EDGE_PP
    return True


def model_path(target: str, model_name: str) -> Path:
    return Path(settings.model_dir) / f"{target}__{model_name}.joblib"


def needs_initial_training(db: Session) -> bool:
    return db.scalar(select(ModelRun.id).limit(1)) is None


# --------------------------------------------------------------------------
# Training
# --------------------------------------------------------------------------


def train_all(db: Session, feats: pd.DataFrame) -> dict[str, dict]:
    Path(settings.model_dir).mkdir(parents=True, exist_ok=True)
    feature_cols = F.feature_columns(feats)
    summary: dict[str, dict] = {}

    for target, horizon in TARGETS.items():
        label = LABEL_COL[target]
        if label not in feats.columns:
            continue

        results = FC.walk_forward_evaluate(
            feats, label, feature_cols, horizon=horizon, n_folds=5
        )
        agg = FC.summarize(results)
        if agg.empty:
            log.warning("no evaluation folds for %s", target)
            continue

        labelled = feats.dropna(subset=[label])
        dates = labelled.index.get_level_values("date")
        train_start = dates.min().date() if len(dates) else None
        train_end = dates.max().date() if len(dates) else None

        # Deactivate the previous generation before writing the new one.
        db.execute(
            update(ModelRun).where(ModelRun.target == target).values(is_active=False)
        )

        target_summary = {}
        for row in agg.itertuples(index=False):
            passed = _passes_gate(
                row.roc_auc, row.lift, row.edge_vs_baseline, row.base_rate
            )

            run = ModelRun(
                target=target,
                model=row.model,
                n_train=len(labelled),
                n_features=len(feature_cols),
                train_start=train_start,
                train_end=train_end,
                roc_auc=float(row.roc_auc) if np.isfinite(row.roc_auc) else None,
                base_rate=float(row.base_rate),
                accuracy=float(row.accuracy),
                baseline_accuracy=float(row.baseline_accuracy),
                edge_vs_baseline=float(row.edge_vs_baseline),
                top_decile_precision=float(row.top_decile_precision),
                lift=float(row.lift) if np.isfinite(row.lift) else None,
                is_active=bool(passed),
                metrics={
                    "folds": int(row.folds),
                    "brier": float(row.brier),
                    "horizon_days": horizon,
                    "passed_gate": bool(passed),
                    "gate": {"min_auc": MIN_AUC, "min_lift": MIN_LIFT,
                             "min_edge_pp": MIN_EDGE_PP,
                             "edge_applies": BALANCED_BAND[0] <= row.base_rate <= BALANCED_BAND[1]},
                    "per_fold": [
                        {
                            "test_start": r.test_start,
                            "test_end": r.test_end,
                            "roc_auc": r.roc_auc,
                            "accuracy": r.accuracy,
                            "baseline_accuracy": r.baseline_accuracy,
                            "lift": r.lift,
                        }
                        for r in results
                        if r.model == row.model
                    ],
                },
            )
            db.add(run)

            # Fit and persist regardless of the gate: a model that fails today
            # may pass after the next retrain, and refitting is the slow part.
            fitted = FC.fit_final(feats, label, feature_cols, row.model)
            if fitted is not None:
                joblib.dump(
                    {"model": fitted, "feature_cols": feature_cols},
                    model_path(target, row.model),
                )

            target_summary[row.model] = {
                "roc_auc": round(float(row.roc_auc), 4),
                "edge_vs_baseline": round(float(row.edge_vs_baseline), 3),
                "lift": round(float(row.lift), 3) if np.isfinite(row.lift) else None,
                "active": bool(passed),
            }

        db.commit()
        summary[target] = target_summary
        log.info("trained %s: %s", target, target_summary)

    return summary


# --------------------------------------------------------------------------
# Prediction
# --------------------------------------------------------------------------


def _active_models(db: Session) -> list[ModelRun]:
    return list(
        db.scalars(
            select(ModelRun).where(ModelRun.is_active.is_(True)).order_by(ModelRun.trained_at.desc())
        )
    )


def predict_all(db: Session, feats: pd.DataFrame, as_of: date) -> int:
    """Score today's rows with every model that passed the gate."""
    runs = _active_models(db)
    if not runs:
        log.info("no active models — nothing to predict")
        return 0

    written = 0
    seen: set[tuple[str, str]] = set()

    for run in runs:
        key = (run.target, run.model)
        if key in seen:  # only the newest run per target/model
            continue
        seen.add(key)

        path = model_path(run.target, run.model)
        if not path.exists():
            log.warning("model artefact missing: %s", path)
            continue

        payload = joblib.load(path)
        model, feature_cols = payload["model"], payload["feature_cols"]
        missing = [c for c in feature_cols if c not in feats.columns]
        if missing:
            # A feature was added or renamed since training; predicting anyway
            # would silently misalign columns.
            log.warning("skipping %s: features changed since training (%s...)", key, missing[:3])
            continue

        label = LABEL_COL[run.target]
        latest = feats[feats.index.get_level_values("date").date == as_of]
        pending = latest[latest[label].isna()]
        if pending.empty:
            continue

        proba = model.predict_proba(pending[feature_cols])[:, 1]
        pct = pd.Series(proba).rank(pct=True).to_numpy() * 100

        rows = [
            {
                "symbol": sym,
                "as_of": as_of,
                "target": run.target,
                "model": run.model,
                "probability": float(p),
                "percentile": float(q),
            }
            for (sym, _), p, q in zip(pending.index, proba, pct)
            if np.isfinite(p)
        ]
        if not rows:
            continue

        stmt = pg_insert(Prediction).values(rows)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_predictions_key",
            set_={"probability": stmt.excluded.probability,
                  "percentile": stmt.excluded.percentile},
        )
        db.execute(stmt)
        written += len(rows)

    db.commit()
    return written
