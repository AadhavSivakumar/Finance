"""Earnings proximity, sector-relative returns and the direction-agnostic label."""

import numpy as np
import pandas as pd
import pytest

from app.services import features as F
from app.services import labels as L
from tests.test_features import BARS, _synthetic_bars


# ---------------------------------------------------------------------------
# Earnings features
# ---------------------------------------------------------------------------


def _earnings_for(symbol: str, dates: list[str]) -> pd.DataFrame:
    return pd.DataFrame({"symbol": symbol, "earnings_date": pd.to_datetime(dates)})


def test_days_to_earnings_counts_down_and_is_capped():
    bars = BARS[BARS["symbol"] == "AAA"]
    # One earnings date well inside the history.
    edate = bars["date"].iloc[200]
    feats = F.build_features(bars, earnings=_earnings_for("AAA", [str(edate.date())]))
    s = feats.xs("AAA", level="symbol")

    assert s.loc[edate, "days_to_earnings"] == 0
    day_before = bars["date"].iloc[199]
    assert s.loc[day_before, "days_to_earnings"] == (edate - day_before).days
    # Far before the date it is capped, never a large number that would leak
    # "this date was known 6 months out".
    far = bars["date"].iloc[50]
    assert s.loc[far, "days_to_earnings"] == F.EARNINGS_HORIZON_DAYS
    # After the last known date there is no "next", so it reads as not soon.
    after = bars["date"].iloc[-1]
    assert s.loc[after, "days_to_earnings"] == F.EARNINGS_HORIZON_DAYS


def test_days_since_earnings_is_backward_looking_only():
    bars = BARS[BARS["symbol"] == "AAA"]
    edate = bars["date"].iloc[200]
    feats = F.build_features(bars, earnings=_earnings_for("AAA", [str(edate.date())]))
    s = feats.xs("AAA", level="symbol")

    assert s.loc[edate, "days_since_earnings"] == 0
    later = bars["date"].iloc[210]
    assert s.loc[later, "days_since_earnings"] == (later - edate).days
    # Before any known date there is nothing to measure since.
    assert np.isnan(s.loc[bars["date"].iloc[100], "days_since_earnings"])


def test_earnings_within_5d_flag():
    bars = BARS[BARS["symbol"] == "AAA"]
    edate = bars["date"].iloc[200]
    feats = F.build_features(bars, earnings=_earnings_for("AAA", [str(edate.date())]))
    s = feats.xs("AAA", level="symbol")
    assert s.loc[bars["date"].iloc[197], "earnings_within_5d"] == 1.0
    assert s.loc[bars["date"].iloc[150], "earnings_within_5d"] == 0.0


def test_no_earnings_table_yields_nan_not_crash():
    feats = F.build_features(BARS, earnings=None)
    assert feats["days_to_earnings"].isna().all()
    assert "days_to_earnings" in F.feature_columns(feats)


def test_earnings_features_do_not_break_the_leakage_guard():
    """Appending future bars must still leave past feature values unchanged."""
    edates = _earnings_for("AAA", ["2023-06-15", "2023-09-14", "2024-01-25"])
    cutoff = BARS["date"].unique()[300]
    early = F.build_features(BARS[BARS["date"] <= cutoff], earnings=edates)
    full = F.build_features(BARS, earnings=edates)
    aligned = full.loc[early.index, early.columns]
    pd.testing.assert_frame_equal(early.sort_index(), aligned.sort_index(), check_exact=False, rtol=1e-12)


# ---------------------------------------------------------------------------
# Sector-relative
# ---------------------------------------------------------------------------


def test_sector_relative_is_stock_minus_its_sector_etf():
    bars = _synthetic_bars(symbols=("SPY", "^VIX", "XLK", "AAA"), n=300)
    feats = F.build_features(bars, sector_map={"AAA": "XLK"})
    a = feats.xs("AAA", level="symbol")
    xlk = feats.xs("XLK", level="symbol")
    expected = a["ret_21d"] - xlk["ret_21d"]
    got = a["rel_sector_21d"]
    # Features are float32; recomputing the difference from two float32 inputs
    # differs from the float64-then-cast stored value by a few ulps. 1e-4 is
    # far tighter than any indicator needs and far looser than float32 noise.
    pd.testing.assert_series_equal(
        got.dropna().astype("float64"), expected.dropna().astype("float64"),
        check_names=False, rtol=1e-4, atol=1e-4,
    )


def test_symbols_without_a_sector_get_nan_relative_return():
    bars = _synthetic_bars(symbols=("SPY", "XLK", "AAA", "BBB"), n=300)
    feats = F.build_features(bars, sector_map={"AAA": "XLK"})
    assert feats.xs("BBB", level="symbol")["rel_sector_21d"].isna().all()


# ---------------------------------------------------------------------------
# Direction-agnostic label
# ---------------------------------------------------------------------------


def test_absmove_label_fires_on_large_moves_in_either_direction():
    feats = L.add_labels(F.build_features(BARS), BARS)
    g = feats.xs("AAA", level="symbol").dropna(subset=["label_absmove_2atr"])
    expected = g["fwd_ret_1d"].abs() > g["_spike_threshold_pct"]
    assert (g["label_absmove_2atr"].astype(bool) == expected).all()


def test_absmove_is_a_superset_of_upside_spike():
    """Every upside spike is also a large absolute move; the reverse is not true."""
    feats = L.add_labels(F.build_features(BARS), BARS)
    both = feats.dropna(subset=["label_spike_2atr", "label_absmove_2atr"])
    up = both["label_spike_2atr"].astype(bool)
    absm = both["label_absmove_2atr"].astype(bool)
    assert (absm | ~up).all()            # up  ->  absmove
    assert absm.sum() > up.sum()         # and there are downside moves too


def test_absmove_base_rate_is_roughly_double_the_upside_rate():
    feats = L.add_labels(F.build_features(BARS), BARS)
    rates = L.base_rates(feats)
    ratio = rates["label_absmove_2atr"] / rates["label_spike_2atr"]
    # Symmetric synthetic returns -> about 2x. Wide band; this is a sanity
    # check on the definition, not a distributional claim.
    assert 1.4 < ratio < 2.8, ratio
