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


# --------------------------------------------------------------------------
# Trend strength / oscillators
# --------------------------------------------------------------------------


def adx(high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14) -> pd.Series:
    """Average Directional Index -- how strongly a market is trending.

    Direction-agnostic on purpose: ADX is high in a strong downtrend as well as
    a strong uptrend. Conventionally, above 25 means trending, below 20 means
    ranging.
    """
    up_move = high.diff()
    down_move = -low.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)

    atr_ = true_range(high, low, close).ewm(alpha=1 / window, adjust=False).mean()
    safe_atr = atr_.replace(0, np.nan)
    plus_di = 100 * plus_dm.ewm(alpha=1 / window, adjust=False).mean() / safe_atr
    minus_di = 100 * minus_dm.ewm(alpha=1 / window, adjust=False).mean() / safe_atr

    denom = (plus_di + minus_di).replace(0, np.nan)
    dx = 100 * (plus_di - minus_di).abs() / denom
    return dx.ewm(alpha=1 / window, adjust=False).mean()


def stochastic_k(
    high: pd.Series, low: pd.Series, close: pd.Series, window: int = 14
) -> pd.Series:
    """Where the close sits within the recent high-low range, 0-100."""
    lowest = low.rolling(window, min_periods=window).min()
    highest = high.rolling(window, min_periods=window).max()
    span = (highest - lowest).replace(0, np.nan)
    return 100 * (close - lowest) / span


def money_flow_index(
    high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series, window: int = 14
) -> pd.Series:
    """RSI weighted by dollar volume -- "is the move backed by money?"."""
    typical = (high + low + close) / 3
    flow = typical * volume
    direction = typical.diff()

    positive = flow.where(direction > 0, 0.0).rolling(window, min_periods=window).sum()
    negative = flow.where(direction < 0, 0.0).rolling(window, min_periods=window).sum()

    ratio = positive / negative.replace(0, np.nan)
    out = 100 - (100 / (1 + ratio))
    # No down-flow at all means a maximal reading, which the division makes NaN.
    return out.where(negative != 0, 100.0)


def obv_trend(close: pd.Series, volume: pd.Series, window: int = 20) -> pd.Series:
    """Slope of On-Balance Volume, normalised by average volume.

    Raw OBV is an unbounded cumulative sum, so its *level* is meaningless
    across symbols; only its recent direction carries information.
    """
    sign = np.sign(close.diff()).fillna(0.0)
    obv = (sign * volume).cumsum()
    change = obv.diff(window)
    scale = volume.rolling(window, min_periods=window).mean().replace(0, np.nan)
    return change / (scale * window)


# --------------------------------------------------------------------------
# Risk-adjusted return and distribution shape
# --------------------------------------------------------------------------


def downside_deviation(close: pd.Series, window: int = 60) -> pd.Series:
    """Annualised volatility of NEGATIVE returns only.

    Standard deviation punishes upside surprises equally with downside ones,
    which is not how anyone experiences risk.
    """
    r = log_returns(close)
    downside = r.where(r < 0, 0.0)
    return downside.rolling(window, min_periods=window).std(ddof=1) * np.sqrt(TRADING_DAYS) * 100


def sharpe_ratio(close: pd.Series, window: int = 60) -> pd.Series:
    """Annualised return divided by annualised volatility.

    Excess-return-free: no risk-free rate is subtracted, so this is strictly a
    return-per-unit-of-risk ratio rather than a true Sharpe. Stated plainly
    because quoting it as "Sharpe" while omitting the risk-free rate is a
    common way to flatter a number.
    """
    r = log_returns(close)
    mean = r.rolling(window, min_periods=window).mean() * TRADING_DAYS
    sd = r.rolling(window, min_periods=window).std(ddof=1) * np.sqrt(TRADING_DAYS)
    return mean / sd.replace(0, np.nan)


def sortino_ratio(close: pd.Series, window: int = 60) -> pd.Series:
    """Like the ratio above but dividing by downside deviation only."""
    r = log_returns(close)
    mean = r.rolling(window, min_periods=window).mean() * TRADING_DAYS
    downside = r.where(r < 0, 0.0)
    dd = downside.rolling(window, min_periods=window).std(ddof=1) * np.sqrt(TRADING_DAYS)
    return mean / dd.replace(0, np.nan)


def ulcer_index(close: pd.Series, window: int = 60) -> pd.Series:
    """Root-mean-square drawdown over the window.

    Unlike max drawdown, which is a single worst moment, this captures how
    *deep and how long* the pain lasted.
    """
    roll_max = close.rolling(window, min_periods=window).max()
    drawdown = ((close - roll_max) / roll_max.replace(0, np.nan)) * 100
    return np.sqrt((drawdown**2).rolling(window, min_periods=window).mean())


def return_skew(close: pd.Series, window: int = 120) -> pd.Series:
    """Asymmetry of the return distribution.

    Negative skew means occasional large losses among many small gains -- the
    shape that ruins people who only looked at average return.
    """
    return log_returns(close).rolling(window, min_periods=window).skew()


def return_kurtosis(close: pd.Series, window: int = 120) -> pd.Series:
    """Fat-tailedness. Above 0 (excess) means extremes are likelier than a
    normal distribution predicts -- which is nearly always true of markets."""
    return log_returns(close).rolling(window, min_periods=window).kurt()


def rolling_correlation(
    asset_close: pd.Series, bench_close: pd.Series, window: int = 60
) -> pd.Series:
    """Correlation of daily returns against a benchmark, aligned on shared dates."""
    a = log_returns(asset_close)
    b = log_returns(bench_close)
    joined = pd.concat([a, b], axis=1, join="inner")
    return joined.iloc[:, 0].rolling(window, min_periods=window // 2).corr(joined.iloc[:, 1])
