"""Model training and honest evaluation.

The models here are ordinary. The *evaluation* is the part that matters, so
most of this file is about not fooling ourselves.

Three specific defences:

1. **Walk-forward, expanding window.** Train on the past, test on the future,
   repeatedly. Random k-fold on a time series trains on tomorrow to predict
   yesterday and is meaningless here.

2. **Purge / embargo between train and test.** A label at date t depends on
   prices through t+horizon. Without an embargo of `horizon` days, the last
   few training labels overlap the first test period, and the model is
   partially told the answer.

3. **Baselines reported alongside every score.** `label_up_5d` has a base rate
   well above 50% because equities drift upward. A model scoring 54% accuracy
   against a 54% majority-class baseline has learned nothing, and only the
   comparison makes that visible.

Preprocessing (imputation, scaling) is fitted inside the pipeline on TRAIN
folds only. Fitting an imputer on the whole dataset is a quiet leak: the
median encodes information from the test period.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from datetime import date

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, roc_auc_score
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

log = logging.getLogger(__name__)

# Top-decile precision: if you acted only on the strongest signals, how often
# would you be right? Far more decision-relevant than overall accuracy.
TOP_K_FRACTION = 0.10


# --------------------------------------------------------------------------
# Splitting
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class Fold:
    train_end: date
    test_start: date
    test_end: date


def purged_walk_forward(
    dates: pd.Index, n_folds: int = 5, horizon: int = 5, min_train_frac: float = 0.4
) -> list[Fold]:
    """Expanding-window folds with a `horizon`-day embargo before each test.

    The embargo is the whole point: labels near the end of a training window
    are computed from prices that fall inside the test window.
    """
    unique = pd.DatetimeIndex(sorted(pd.unique(dates)))
    n = len(unique)
    if n < 50:
        return []

    start = int(n * min_train_frac)
    remaining = n - start
    block = remaining // n_folds
    if block <= horizon:
        return []

    folds: list[Fold] = []
    for i in range(n_folds):
        train_end_idx = start + i * block
        test_start_idx = train_end_idx + horizon  # embargo
        test_end_idx = min(train_end_idx + block, n - 1)
        if test_start_idx >= test_end_idx:
            continue
        folds.append(
            Fold(
                train_end=unique[train_end_idx].date(),
                test_start=unique[test_start_idx].date(),
                test_end=unique[test_end_idx].date(),
            )
        )
    return folds


# --------------------------------------------------------------------------
# Models
# --------------------------------------------------------------------------


def build_models() -> dict[str, Pipeline]:
    """Two deliberately different model families.

    If the linear model matches the boosted one, that is a real finding: it
    means the signal is weak and roughly linear, and the extra capacity is
    fitting noise.
    """
    return {
        "logistic": Pipeline(
            [
                ("impute", SimpleImputer(strategy="median")),
                ("scale", StandardScaler()),
                (
                    "clf",
                    LogisticRegression(
                        max_iter=2000,
                        C=0.1,  # strong regularisation: financial features are
                                # collinear and the signal-to-noise is awful
                        class_weight="balanced",
                    ),
                ),
            ]
        ),
        "gradient_boosting": Pipeline(
            [
                # HistGradientBoosting handles NaN natively, but imputing keeps
                # both pipelines fed identically so the comparison is fair.
                ("impute", SimpleImputer(strategy="median")),
                (
                    "clf",
                    HistGradientBoostingClassifier(
                        max_depth=3,          # shallow on purpose
                        max_iter=200,
                        learning_rate=0.05,
                        l2_regularization=1.0,
                        early_stopping=True,
                        validation_fraction=0.15,
                        random_state=0,
                    ),
                ),
            ]
        ),
    }


# --------------------------------------------------------------------------
# Metrics
# --------------------------------------------------------------------------


@dataclass
class FoldResult:
    model: str
    label: str
    test_start: str
    test_end: str
    n_train: int
    n_test: int
    base_rate: float          # % positives in test -- the majority baseline
    accuracy: float
    baseline_accuracy: float  # always predict the training majority class
    roc_auc: float
    brier: float
    precision_at_top_decile: float
    lift: float               # top-decile precision / base rate


def _evaluate(
    name: str, label: str, y_true: np.ndarray, proba: np.ndarray, y_train: np.ndarray,
    fold: Fold, n_train: int
) -> FoldResult:
    base_rate = float(y_true.mean())
    majority = float(y_train.mean() > 0.5)
    baseline_acc = float((y_true == majority).mean())

    preds = (proba >= 0.5).astype(float)
    accuracy = float((preds == y_true).mean())

    try:
        auc = float(roc_auc_score(y_true, proba)) if len(np.unique(y_true)) > 1 else float("nan")
    except ValueError:
        auc = float("nan")

    k = max(1, int(len(proba) * TOP_K_FRACTION))
    top_idx = np.argsort(proba)[-k:]
    top_precision = float(y_true[top_idx].mean())

    return FoldResult(
        model=name,
        label=label,
        test_start=fold.test_start.isoformat(),
        test_end=fold.test_end.isoformat(),
        n_train=n_train,
        n_test=len(y_true),
        base_rate=base_rate * 100,
        accuracy=accuracy * 100,
        baseline_accuracy=baseline_acc * 100,
        roc_auc=auc,
        brier=float(brier_score_loss(y_true, proba)),
        precision_at_top_decile=top_precision * 100,
        lift=float(top_precision / base_rate) if base_rate > 0 else float("nan"),
    )


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------


def walk_forward_evaluate(
    frame: pd.DataFrame,
    label: str,
    feature_cols: list[str],
    horizon: int = 5,
    n_folds: int = 5,
) -> list[FoldResult]:
    """Train and score each model on every fold. Returns per-fold results."""
    data = frame.dropna(subset=[label]).copy()
    if data.empty:
        return []

    dates = data.index.get_level_values("date")
    folds = purged_walk_forward(dates, n_folds=n_folds, horizon=horizon)
    if not folds:
        log.warning("not enough history for walk-forward on %s", label)
        return []

    results: list[FoldResult] = []
    for fold in folds:
        train_mask = dates.date <= fold.train_end
        test_mask = (dates.date >= fold.test_start) & (dates.date <= fold.test_end)

        X_train = data.loc[train_mask, feature_cols]
        y_train = data.loc[train_mask, label].astype(float).to_numpy()
        X_test = data.loc[test_mask, feature_cols]
        y_test = data.loc[test_mask, label].astype(float).to_numpy()

        # A fold with a single class cannot be trained or scored meaningfully.
        if len(y_train) < 200 or len(y_test) < 20 or len(np.unique(y_train)) < 2:
            continue

        for name, model in build_models().items():
            try:
                model.fit(X_train, y_train)
                proba = model.predict_proba(X_test)[:, 1]
            except Exception as exc:  # noqa: BLE001
                log.warning("%s failed on fold %s: %s", name, fold.test_start, exc)
                continue
            results.append(
                _evaluate(name, label, y_test, proba, y_train, fold, len(y_train))
            )
    return results


def summarize(results: list[FoldResult]) -> pd.DataFrame:
    """Average each model's metrics across folds."""
    if not results:
        return pd.DataFrame()
    df = pd.DataFrame([asdict(r) for r in results])
    agg = (
        df.groupby(["label", "model"])
        .agg(
            folds=("accuracy", "size"),
            base_rate=("base_rate", "mean"),
            accuracy=("accuracy", "mean"),
            baseline_accuracy=("baseline_accuracy", "mean"),
            roc_auc=("roc_auc", "mean"),
            brier=("brier", "mean"),
            top_decile_precision=("precision_at_top_decile", "mean"),
            lift=("lift", "mean"),
        )
        .reset_index()
    )
    # The only column that matters for "is this real": edge over the baseline.
    agg["edge_vs_baseline"] = agg["accuracy"] - agg["baseline_accuracy"]
    return agg.round(3)


def fit_final(
    frame: pd.DataFrame, label: str, feature_cols: list[str], model_name: str
) -> Pipeline | None:
    """Refit on all labelled history, for scoring today's unlabelled rows."""
    data = frame.dropna(subset=[label])
    y = data[label].astype(float).to_numpy()
    if len(y) < 200 or len(np.unique(y)) < 2:
        return None
    model = build_models()[model_name]
    model.fit(data[feature_cols], y)
    return model


def predict_latest(
    model: Pipeline, frame: pd.DataFrame, label: str, feature_cols: list[str]
) -> pd.DataFrame:
    """Score the rows whose outcome has not happened yet -- i.e. the ones we
    actually care about predicting."""
    pending = frame[frame[label].isna()]
    if pending.empty:
        return pd.DataFrame()
    proba = model.predict_proba(pending[feature_cols])[:, 1]
    return pd.DataFrame({"probability": proba}, index=pending.index)
