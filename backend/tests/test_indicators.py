"""Indicator math checked against hand-computable cases.

These are deliberately not snapshot tests. Every expected value here is one a
human can derive on paper -- RSI is exactly 100 on an unbroken run of gains,
beta against yourself is exactly 1.0, a 100->50 drawdown is exactly -50%. A
snapshot test would happily lock in a wrong number.

Run:  docker compose exec api python -m pytest tests/ -q
"""

import numpy as np
import pandas as pd
import pytest

from app.services import indicators as I

IDX = pd.date_range("2025-01-01", periods=300, freq="B")
RNG = np.random.default_rng(42)

RAMP = pd.Series(np.arange(1.0, 301.0), index=IDX)
FALL = pd.Series(np.arange(300.0, 0.0, -1.0), index=IDX)
NOISY = pd.Series(100 + np.cumsum(RNG.normal(0, 1, 300)), index=IDX)
BENCH = pd.Series(100 * np.cumprod(1 + RNG.normal(0, 0.01, 300)), index=IDX)


def test_sma_is_the_mean_of_the_window():
    assert I.sma(RAMP, 5).iloc[-1] == 298.0  # mean(296..300)


def test_rsi_pegs_at_extremes():
    assert I.rsi(RAMP, 14).iloc[-1] == pytest.approx(100.0)
    assert I.rsi(FALL, 14).iloc[-1] == pytest.approx(0.0)


def test_rsi_stays_bounded_on_noise():
    r = I.rsi(NOISY, 14).dropna()
    assert r.between(0, 100).all()
    assert 20 < r.mean() < 80


def test_macd_histogram_is_line_minus_signal():
    m = I.macd(RAMP)
    assert list(m.columns) == ["macd", "signal", "histogram"]
    assert m["macd"].iloc[-1] > 0  # sustained uptrend
    assert (m["macd"] - m["signal"]).iloc[-1] == pytest.approx(m["histogram"].iloc[-1])


def test_bollinger_bands_are_ordered():
    b = I.bollinger(NOISY)
    # Drop warm-up rows FIRST: comparing against NaN yields False, not NaN,
    # so filtering the boolean result afterwards would silently keep them.
    valid = b[["upper", "middle", "lower"]].dropna()
    assert len(valid) > 100
    assert ((valid["upper"] > valid["middle"]) & (valid["middle"] > valid["lower"])).all()


def test_bollinger_bandwidth_is_zero_for_a_flat_series():
    flat = pd.Series(np.full(300, 50.0), index=IDX)
    assert I.bollinger(flat)["bandwidth"].dropna().eq(0).all()


def test_constant_growth_has_zero_volatility():
    steady = pd.Series(100 * 1.01 ** np.arange(300), index=IDX)
    assert I.realized_volatility(steady).iloc[-1] == pytest.approx(0.0, abs=1e-9)


def test_max_drawdown():
    dd = pd.Series([100, 90, 50, 60, 75.0], index=IDX[:5])
    assert I.max_drawdown(dd) == pytest.approx(-50.0)
    assert I.max_drawdown(RAMP) == 0.0  # monotonic up never draws down


def test_beta_of_self_is_one_and_leverage_scales():
    assert I.beta(BENCH, BENCH) == pytest.approx(1.0)
    lev_returns = 2 * np.diff(np.log(BENCH), prepend=np.log(BENCH.iloc[0]))
    lev = pd.Series(100 * np.cumprod(1 + lev_returns), index=IDX)
    assert I.beta(lev, BENCH) == pytest.approx(2.0, abs=0.05)


def test_trailing_return():
    assert I.trailing_return(pd.Series([100, 110.0], index=IDX[:2]), 1) == pytest.approx(10.0)


def test_distance_from_extremes():
    from_high, from_low = I.distance_from_extreme(pd.Series([100, 200, 150.0], index=IDX[:3]))
    assert from_high == pytest.approx(-25.0)
    assert from_low == pytest.approx(50.0)


def test_volume_zscore_flags_a_spike():
    base = pd.Series(RNG.normal(1_000_000, 80_000, 25), index=IDX[:25])
    vol = pd.concat([base, pd.Series([10_000_000.0], index=IDX[25:26])])
    assert I.volume_zscore(vol) > 3


def test_volume_zscore_is_undefined_for_zero_variance():
    """Real volume is never perfectly flat, but the guard must not divide by zero."""
    flat = pd.Series([1000.0] * 25 + [10000.0], index=IDX[:26])
    assert np.isnan(I.volume_zscore(flat))


def test_correlation_matrix():
    frame = pd.DataFrame({"a": BENCH, "b": BENCH, "c": 1 / BENCH})
    cm = I.correlation_matrix(frame)
    assert cm.loc["a", "b"] == pytest.approx(1.0)
    assert cm.loc["a", "c"] < -0.99
