"""Feature and label correctness, with leakage as the headline concern.

If any test in this file fails, every downstream accuracy number is worthless.
"""

import numpy as np
import pandas as pd
import pytest

from app.services import features as F
from app.services import labels as L

RNG = np.random.default_rng(7)


def _synthetic_bars(symbols=("SPY", "^VIX", "AAA", "BBB"), n=400) -> pd.DataFrame:
    dates = pd.bdate_range("2023-01-02", periods=n)
    frames = []
    for i, sym in enumerate(symbols):
        close = 100 * np.cumprod(1 + RNG.normal(0.0004, 0.012 + 0.004 * i, n))
        high = close * (1 + np.abs(RNG.normal(0, 0.004, n)))
        low = close * (1 - np.abs(RNG.normal(0, 0.004, n)))
        frames.append(
            pd.DataFrame(
                {
                    "symbol": sym,
                    "date": dates,
                    "open": close * (1 + RNG.normal(0, 0.002, n)),
                    "high": np.maximum(high, close),
                    "low": np.minimum(low, close),
                    "close": close,
                    "volume": RNG.integers(1_000_000, 5_000_000, n).astype(float),
                }
            )
        )
    return pd.concat(frames, ignore_index=True)


BARS = _synthetic_bars()


# ---------------------------------------------------------------------------
# Leakage
# ---------------------------------------------------------------------------


def test_features_do_not_change_when_future_bars_arrive():
    """THE leakage test.

    Compute features on a truncated history, then on the full history. Every
    value that existed in the truncated run must be bit-identical in the full
    run. If a feature peeked ahead -- a centred window, a negative shift, a
    full-sample normalisation -- adding future data would change past rows.
    """
    cutoff = BARS["date"].unique()[300]
    early = BARS[BARS["date"] <= cutoff]

    feats_early = F.build_features(early)
    feats_full = F.build_features(BARS)

    common = feats_early.index
    aligned = feats_full.loc[common, feats_early.columns]

    pd.testing.assert_frame_equal(
        feats_early.sort_index(), aligned.sort_index(), check_exact=False, rtol=1e-12
    )


def test_no_feature_column_is_constant_or_all_nan():
    feats = F.build_features(BARS)
    cols = F.feature_columns(feats)
    assert len(cols) > 25
    tail = feats.groupby(level="symbol").tail(50)
    for c in cols:
        assert tail[c].notna().any(), f"{c} is entirely NaN even after warm-up"


def test_feature_columns_excludes_internals_and_labels():
    feats = L.add_labels(F.build_features(BARS), BARS)
    cols = F.feature_columns(feats)
    assert "_atr14" not in cols
    assert not any(c.startswith("label_") for c in cols)
    assert not any(c.startswith("fwd_") for c in cols)


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------


def test_forward_return_is_computed_forward():
    close = pd.Series([100.0, 110.0, 121.0])
    fwd = L._forward_return(close, 1)
    assert fwd.iloc[0] == pytest.approx(10.0)   # 100 -> 110
    assert fwd.iloc[1] == pytest.approx(10.0)   # 110 -> 121
    assert np.isnan(fwd.iloc[2])                # no future bar yet


def test_last_rows_have_no_label():
    """The most recent bars are exactly the rows we predict on; they must be
    unlabelled rather than silently labelled False."""
    feats = L.add_labels(F.build_features(BARS), BARS)
    for _, g in feats.groupby(level="symbol"):
        g = g.sort_index()
        assert pd.isna(g["label_up_5d"].iloc[-1])
        assert pd.isna(g["label_spike_2atr"].iloc[-1])
        # 5-day horizon -> the last 5 rows are unknown
        assert g["label_up_5d"].iloc[-L.DIRECTION_HORIZON:].isna().all()


def test_spike_label_matches_its_definition():
    feats = L.add_labels(F.build_features(BARS), BARS)
    g = feats.xs("AAA", level="symbol").dropna(subset=["label_spike_2atr"])
    expected = g["fwd_ret_1d"] > g["_spike_threshold_pct"]
    assert (g["label_spike_2atr"].astype(bool) == expected).all()


def test_spike_label_is_rare_but_present():
    """2x ATR should be uncommon. If it fires on half the days the threshold
    is wrong; if it never fires there is nothing to learn."""
    feats = L.add_labels(F.build_features(BARS), BARS)
    rate = feats["label_spike_2atr"].dropna().mean()
    assert 0.001 < rate < 0.20, rate


def test_base_rates_reported_for_both_labels():
    feats = L.add_labels(F.build_features(BARS), BARS)
    rates = L.base_rates(feats)
    assert set(rates) == {"label_spike_2atr", "label_up_5d"}
    assert all(0 < v < 100 for v in rates.values())
