"""Validation-harness correctness.

The models are replaceable; the harness is not. If it reports edge on pure
noise, every result it ever produces is fiction. These tests calibrate it in
both directions: no edge on noise, real edge on planted signal.
"""

import numpy as np
import pandas as pd
import pytest

from app.services import forecasting as FC

RNG = np.random.default_rng(11)
FEATURES = [f"f{i}" for i in range(8)]


def _panel(n_dates=500, n_symbols=12, signal_strength=0.0):
    """Synthetic panel. signal_strength=0 -> label is pure coin flip."""
    dates = pd.bdate_range("2022-01-03", periods=n_dates)
    rows = []
    for s in range(n_symbols):
        X = RNG.normal(size=(n_dates, len(FEATURES)))
        # Only f0 carries signal, and only when asked for.
        logit = signal_strength * X[:, 0]
        p = 1 / (1 + np.exp(-logit))
        y = RNG.random(n_dates) < p
        d = pd.DataFrame(X, columns=FEATURES)
        d["symbol"] = f"S{s}"
        d["date"] = dates
        d["label_test"] = y.astype(float)
        rows.append(d)
    return pd.concat(rows).set_index(["symbol", "date"]).sort_index()


# ---------------------------------------------------------------------------
# Splitting
# ---------------------------------------------------------------------------


def test_folds_are_ordered_and_respect_the_embargo():
    dates = pd.bdate_range("2022-01-03", periods=500)
    horizon = 5
    folds = FC.purged_walk_forward(dates, n_folds=5, horizon=horizon)
    assert len(folds) >= 3

    for f in folds:
        # Test must start strictly after training ends, by at least the label
        # horizon -- otherwise training labels overlap the test window.
        gap = np.busday_count(f.train_end, f.test_start)
        assert gap >= horizon, f"embargo too small: {gap} < {horizon}"
        assert f.test_start < f.test_end

    # Expanding window: each fold trains on strictly more history.
    assert [f.train_end for f in folds] == sorted(f.train_end for f in folds)


def test_no_folds_when_history_is_too_short():
    assert FC.purged_walk_forward(pd.bdate_range("2024-01-01", periods=20)) == []


# ---------------------------------------------------------------------------
# The calibration tests
# ---------------------------------------------------------------------------


def test_harness_reports_no_edge_on_pure_noise():
    """THE anti-self-deception test.

    Labels are independent coin flips, so no model can beat chance. If the
    harness reports meaningful AUC or edge here, it is leaking.
    """
    panel = _panel(signal_strength=0.0)
    results = FC.walk_forward_evaluate(panel, "label_test", FEATURES, horizon=5)
    assert results, "harness produced no folds"

    summary = FC.summarize(results)
    for _, row in summary.iterrows():
        assert 0.42 < row["roc_auc"] < 0.58, f"{row['model']} AUC {row['roc_auc']} on noise"
        assert abs(row["edge_vs_baseline"]) < 6, (
            f"{row['model']} claims {row['edge_vs_baseline']:.1f}pp edge on noise"
        )
        assert 0.6 < row["lift"] < 1.6, f"{row['model']} lift {row['lift']} on noise"


def test_harness_finds_real_signal_when_present():
    """The other direction: a harness that never finds anything is also broken."""
    panel = _panel(signal_strength=1.6)
    results = FC.walk_forward_evaluate(panel, "label_test", FEATURES, horizon=5)
    summary = FC.summarize(results)
    assert (summary["roc_auc"] > 0.65).all(), summary[["model", "roc_auc"]]
    assert (summary["edge_vs_baseline"] > 3).all()


def test_baseline_accuracy_is_reported_for_every_fold():
    panel = _panel(signal_strength=0.0)
    results = FC.walk_forward_evaluate(panel, "label_test", FEATURES, horizon=5)
    for r in results:
        assert 0 <= r.baseline_accuracy <= 100
        assert 0 <= r.base_rate <= 100
        assert r.n_train > 0 and r.n_test > 0


# ---------------------------------------------------------------------------
# Prediction path
# ---------------------------------------------------------------------------


def test_predict_latest_scores_only_unlabelled_rows():
    panel = _panel(signal_strength=1.0)
    panel = panel.copy()
    # Blank the most recent date's labels, mimicking "outcome not yet known".
    last_date = panel.index.get_level_values("date").max()
    panel.loc[panel.index.get_level_values("date") == last_date, "label_test"] = np.nan

    model = FC.fit_final(panel, "label_test", FEATURES, "logistic")
    assert model is not None

    preds = FC.predict_latest(model, panel, "label_test", FEATURES)
    assert len(preds) == 12  # one row per symbol on the final date
    assert preds["probability"].between(0, 1).all()
    assert (preds.index.get_level_values("date") == last_date).all()


def test_fit_final_refuses_single_class_data():
    panel = _panel()
    panel["label_test"] = 1.0
    assert FC.fit_final(panel, "label_test", FEATURES, "logistic") is None
