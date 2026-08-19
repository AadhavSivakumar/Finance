"""Pure technical-analysis math.

Every function here takes plain pandas objects and returns plain numbers or
Series. No database, no network, no config -- which is what makes the whole
analytics layer testable without infrastructure.

Conventions:
  * ``close`` is a float Series indexed by date, ascending, no gaps beyond
    genuine market closures.
  * Returns are simple (not log) unless a docstring says otherwise, because
    they get displayed to humans.
  * Annualisation uses 252 trading days for everything, crypto included. Using
    365 for crypto would make its volatility look ~20% lower than an equity
    with identical daily moves, which defeats the purpose of comparing them.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252


# --------------------------------------------------------------------------
# Trend
# --------------------------------------------------------------------------


def sma(close: pd.Series, window: int) -> pd.Series:
    return close.rolling(window, min_periods=window).mean()


def ema(close: pd.Series, span: int) -> pd.Series:
    return close.ewm(span=span, adjust=False).mean()


def macd(
    close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9
) -> pd.DataFrame:
    line = ema(close, fast) - ema(close, slow)
    sig = line.ewm(span=signal, adjust=False).mean()
    return pd.DataFrame({"macd": line, "signal": sig, "histogram": line - sig})


# --------------------------------------------------------------------------
# Momentum / oscillators
# --------------------------------------------------------------------------


def rsi(close: pd.Series, window: int = 14) -> pd.Series:
    """Relative Strength Index using Wilder's smoothing.

    Wilder's original uses an EMA with alpha = 1/window, NOT a simple rolling
    mean. The simple-mean version is a common and subtly wrong implementation
    that gives noticeably different values on the same data.
    """
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)

    avg_gain = gain.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / window, min_periods=window, adjust=False).mean()

    rs = avg_gain / avg_loss.replace(0, np.nan)
    out = 100 - (100 / (1 + rs))
    # avg_loss == 0 means an unbroken run of gains -> RSI is 100 by definition,
    # but the division above yields NaN, so patch it back.
    return out.where(avg_loss != 0, 100.0).where(avg_gain.notna())


def bollinger(close: pd.Series, window: int = 20, num_std: float = 2.0) -> pd.DataFrame:
    mid = sma(close, window)
    sd = close.rolling(window, min_periods=window).std(ddof=0)
    upper, lower = mid + num_std * sd, mid - num_std * sd
    # %B: where price sits in the band. 0 = lower band, 1 = upper band.
    width = (upper - lower).replace(0, np.nan)
    return pd.DataFrame(
        {
            "middle": mid,
            "upper": upper,
            "lower": lower,
            "percent_b": (close - lower) / width,
            "bandwidth": width / mid.replace(0, np.nan),
        }
    )


# --------------------------------------------------------------------------
# Volatility / risk
# --------------------------------------------------------------------------


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    prev_close = close.shift(1)
    return pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1
    ).max(axis=1)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    return true_range(high, low, close).ewm(
        alpha=1 / window, min_periods=window, adjust=False
    ).mean()


def log_returns(close: pd.Series) -> pd.Series:
    return np.log(close / close.shift(1))


def realized_volatility(close: pd.Series, window: int = 20) -> pd.Series:
    """Annualised standard deviation of log returns, as a percentage."""
    return log_returns(close).rolling(window, min_periods=window).std(ddof=1) * np.sqrt(
        TRADING_DAYS
    ) * 100


def max_drawdown(close: pd.Series) -> float:
    """Worst peak-to-trough decline over the series, as a negative percent."""
    if close.empty:
        return float("nan")
    running_max = close.cummax()
    return float((close / running_max - 1).min() * 100)


def drawdown_series(close: pd.Series) -> pd.Series:
    return (close / close.cummax() - 1) * 100


def beta(asset_close: pd.Series, bench_close: pd.Series, window: int = 60) -> float:
    """Covariance-over-variance beta on the last `window` daily returns.

    Both series are aligned on their shared dates first: crypto trades on
    weekends and equities do not, so an unaligned join silently pairs a
    Saturday crypto move against Friday's equity move.
    """
    a = log_returns(asset_close)
    b = log_returns(bench_close)
    joined = pd.concat([a, b], axis=1, join="inner").dropna().tail(window)
    if len(joined) < 10:
        return float("nan")
    var = joined.iloc[:, 1].var(ddof=1)
    if var == 0 or not np.isfinite(var):
        return float("nan")
    return float(joined.iloc[:, 0].cov(joined.iloc[:, 1]) / var)


def correlation_matrix(closes: pd.DataFrame, window: int = 90) -> pd.DataFrame:
    """Pairwise correlation of daily log returns over the trailing window."""
    rets = np.log(closes / closes.shift(1)).tail(window)
    # min_periods guards against a pair that barely overlaps producing a
    # confident-looking correlation from a handful of points.
    return rets.corr(min_periods=max(10, window // 3))


# --------------------------------------------------------------------------
# Cross-sectional helpers
# --------------------------------------------------------------------------


def trailing_return(close: pd.Series, days: int) -> float:
    """Simple percent return over the last `days` bars."""
    s = close.dropna()
    if len(s) <= days:
        return float("nan")
    past, now = s.iloc[-(days + 1)], s.iloc[-1]
    if past == 0 or not np.isfinite(past):
        return float("nan")
    return float((now / past - 1) * 100)


def distance_from_extreme(close: pd.Series, window: int = 252) -> tuple[float, float]:
    """Percent below the trailing high and above the trailing low."""
    s = close.dropna().tail(window)
    if s.empty:
        return float("nan"), float("nan")
    hi, lo, now = s.max(), s.min(), s.iloc[-1]
    from_high = float((now / hi - 1) * 100) if hi else float("nan")
    from_low = float((now / lo - 1) * 100) if lo else float("nan")
    return from_high, from_low


def volume_zscore(volume: pd.Series, window: int = 20) -> float:
    """How unusual today's volume is, in standard deviations."""
    v = volume.dropna()
    if len(v) < window + 1:
        return float("nan")
    hist = v.iloc[-(window + 1) : -1]
    sd = hist.std(ddof=1)
    if sd == 0 or not np.isfinite(sd):
        return float("nan")
    return float((v.iloc[-1] - hist.mean()) / sd)
