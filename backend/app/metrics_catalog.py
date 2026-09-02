"""What every metric means, in one place.

Defined on the BACKEND rather than in the UI so the API, the static export and
the frontend all describe a number identically. A metric whose definition
lives next to its rendering code inevitably ends up explained two different
ways in two different tables.

Each entry carries:
  label       short display name
  unit        "%", "x", "" -- drives formatting
  short       one line: what it is
  reading     how to interpret a value, including typical ranges
  direction   "higher"/"lower"/"context" -- whether more is better, worse, or
              neither. Deliberately "context" for most of them: a high RSI is
              not good or bad, it is stretched.
  caveat      the thing that makes people misread it (optional)
"""

from __future__ import annotations

from typing import TypedDict


class Metric(TypedDict, total=False):
    key: str
    label: str
    unit: str
    short: str
    reading: str
    direction: str
    caveat: str
    group: str


CATALOG: list[Metric] = [
    # --- returns ---------------------------------------------------------
    {
        "key": "ret_1d", "label": "1-day return", "unit": "%", "group": "Returns",
        "short": "Price change since the previous close.",
        "reading": "Straightforward percentage move. Compare against the instrument's own typical daily range (ATR%) rather than a fixed threshold — 2% is routine for a high-beta stock and extraordinary for a utility.",
        "direction": "context",
    },
    {
        "key": "ret_21d", "label": "1-month return", "unit": "%", "group": "Returns",
        "short": "Price change over the last ~21 trading days.",
        "reading": "The workhorse momentum window. Ranking a universe by this is the basis of most rotation strategies.",
        "direction": "context",
    },
    {
        "key": "ret_252d", "label": "1-year return", "unit": "%", "group": "Returns",
        "short": "Price change over roughly the last year.",
        "reading": "Long-horizon trend. Classic momentum research skips the most recent month, because very recent returns tend to reverse.",
        "direction": "context",
    },
    {
        "key": "rel_strength_21d", "label": "Relative strength", "unit": "%", "group": "Returns",
        "short": "1-month return minus the S&P 500's over the same period.",
        "reading": "Positive means outperforming the market. This separates 'going up' from 'going up more than everything else' — in a strong market almost everything rises, and only this distinguishes leaders.",
        "direction": "higher",
    },
    # --- trend -----------------------------------------------------------
    {
        "key": "px_over_sma200", "label": "vs 200-day average", "unit": "%", "group": "Trend",
        "short": "How far price sits above or below its 200-day moving average.",
        "reading": "The most-watched long-term trend line. Above zero is conventionally 'in an uptrend'. The share of a universe above it is market breadth.",
        "direction": "context",
    },
    {
        "key": "adx_14", "label": "ADX (trend strength)", "unit": "", "group": "Trend",
        "short": "How strongly the instrument is trending, regardless of direction.",
        "reading": "Above 25 suggests a real trend; below 20 suggests chop. It says nothing about which way — ADX is just as high in a crash as in a rally.",
        "direction": "context",
        "caveat": "Frequently misread as bullish. It is direction-blind by construction.",
    },
    # --- oscillators -----------------------------------------------------
    {
        "key": "rsi_14", "label": "RSI (14)", "unit": "", "group": "Momentum",
        "short": "Ratio of recent gains to recent losses, scaled 0–100.",
        "reading": "Above 70 is conventionally 'overbought', below 30 'oversold'. In a strong trend RSI can sit above 70 for weeks, so it is far better as a stretch gauge than a timing signal.",
        "direction": "context",
        "caveat": "'Overbought' does not mean 'about to fall'. Strong trends stay overbought.",
    },
    {
        "key": "stoch_k_14", "label": "Stochastic %K", "unit": "", "group": "Momentum",
        "short": "Where the close sits inside the last 14 days' high-low range.",
        "reading": "100 means closing at the top of the range, 0 at the bottom. Closing strong repeatedly is a sign of demand.",
        "direction": "context",
    },
    {
        "key": "mfi_14", "label": "Money Flow Index", "unit": "", "group": "Momentum",
        "short": "RSI weighted by dollar volume — is the move backed by real money?",
        "reading": "Above 80 / below 20 are the conventional extremes. Divergence from price is the interesting case: a rally on falling money flow lacks participation.",
        "direction": "context",
    },
    {
        "key": "obv_trend_20", "label": "Volume trend (OBV)", "unit": "", "group": "Momentum",
        "short": "Direction of on-balance volume over 20 days, normalised.",
        "reading": "Positive means volume is accumulating on up days. The level is meaningless across symbols; only sign and relative magnitude matter.",
        "direction": "higher",
    },
    # --- volatility / risk ----------------------------------------------
    {
        "key": "vol_20d", "label": "Volatility (20d)", "unit": "%", "group": "Risk",
        "short": "Annualised standard deviation of the last 20 days of returns.",
        "reading": "Roughly, the one-standard-deviation range over a year. 15% is a calm large-cap; 60%+ is a speculative name or a crisis.",
        "direction": "context",
    },
    {
        "key": "vol_ratio_10_60", "label": "Volatility expansion", "unit": "x", "group": "Risk",
        "short": "10-day volatility divided by 60-day volatility.",
        "reading": "Above 1 means volatility is picking up right now versus its recent norm. Sustained readings above ~1.5 often accompany a regime change, and compression below ~0.7 frequently precedes expansion.",
        "direction": "context",
    },
    {
        "key": "atr_pct", "label": "ATR %", "unit": "%", "group": "Risk",
        "short": "Average true range as a percentage of price — the typical daily swing.",
        "reading": "The natural unit for 'is this move big?'. A 3% day is 1x ATR for one stock and 4x for another, which is exactly why the spike model measures moves in ATR rather than percent.",
        "direction": "context",
    },
    {
        "key": "downside_dev_60", "label": "Downside deviation", "unit": "%", "group": "Risk",
        "short": "Volatility computed from negative returns only.",
        "reading": "Standard volatility penalises big up-days as much as big down-days. This isolates the half people actually mind.",
        "direction": "lower",
    },
    {
        "key": "sharpe_60", "label": "Return / risk (60d)", "unit": "", "group": "Risk",
        "short": "Annualised return divided by annualised volatility.",
        "reading": "Above 1 is a good run; above 2 over a short window is usually luck rather than skill.",
        "direction": "higher",
        "caveat": "Not a true Sharpe ratio — no risk-free rate is subtracted, so it reads high when rates are high.",
    },
    {
        "key": "sortino_60", "label": "Sortino (60d)", "unit": "", "group": "Risk",
        "short": "Return divided by downside deviation instead of total volatility.",
        "reading": "Rewards instruments whose volatility is mostly upside. Usually higher than the return/risk ratio for the same instrument.",
        "direction": "higher",
    },
    {
        "key": "ulcer_60", "label": "Ulcer index", "unit": "", "group": "Risk",
        "short": "Root-mean-square drawdown over 60 days — depth *and* duration of pain.",
        "reading": "Max drawdown records one worst moment; this captures how long you sat underwater. Higher is more uncomfortable to hold.",
        "direction": "lower",
    },
    {
        "key": "drawdown_pct", "label": "Drawdown", "unit": "%", "group": "Risk",
        "short": "How far below its running peak the price currently sits.",
        "reading": "Always zero or negative. -50% requires a +100% gain to recover, which is why deep drawdowns matter more than they look.",
        "direction": "higher",
    },
    {
        "key": "skew_120", "label": "Return skew", "unit": "", "group": "Risk",
        "short": "Asymmetry of the return distribution over ~6 months.",
        "reading": "Negative skew means many small gains punctuated by occasional large losses — the profile that looks excellent right up until it does not.",
        "direction": "higher",
    },
    {
        "key": "kurtosis_120", "label": "Fat tails", "unit": "", "group": "Risk",
        "short": "Excess kurtosis of returns — how often extremes happen.",
        "reading": "Above 0 means extreme moves are likelier than a normal distribution implies. Nearly all financial assets show this; large values mean models assuming normality will understate risk badly.",
        "direction": "context",
    },
    {
        "key": "beta_60", "label": "Beta vs S&P 500", "unit": "", "group": "Risk",
        "short": "Sensitivity to market moves over 60 days.",
        "reading": "1.0 moves with the market, 1.5 amplifies it by half, negative moves against it. Beta describes co-movement, not quality.",
        "direction": "context",
    },
    {
        "key": "corr_spy_60", "label": "Correlation to S&P 500", "unit": "", "group": "Risk",
        "short": "How closely daily returns track the market.",
        "reading": "Near 1 means it offers little diversification. Correlations tend to converge toward 1 during crashes, which is precisely when diversification was supposed to help.",
        "direction": "context",
    },
    # --- position --------------------------------------------------------
    {
        "key": "pct_from_52w_high", "label": "From 52-week high", "unit": "%", "group": "Position",
        "short": "Distance below the highest close of the past year.",
        "reading": "Near zero means making new highs, which is historically a momentum signal rather than a warning.",
        "direction": "higher",
    },
    {
        "key": "volume_z", "label": "Volume z-score", "unit": "σ", "group": "Volume",
        "short": "How unusual today's volume is versus its 20-day norm.",
        "reading": "Above 3 means a genuinely unusual day — earnings, news, or an index event. Volume confirms conviction behind a price move.",
        "direction": "context",
    },
]

BY_KEY: dict[str, Metric] = {m["key"]: m for m in CATALOG}


def catalog() -> list[Metric]:
    return CATALOG
