"""Prediction targets.

The asymmetry that matters: a **feature** at date t may only use data up to
t, while a **label** at date t must use only data strictly *after* t. Getting
these backwards in either direction is leakage.

Targets:
  ``label_spike_2atr`` -- does the next day's gain exceed 2x today's ATR?
        Volatility-scaled on purpose. A fixed "+3%" threshold fires constantly
        on NVDA and essentially never on XLU, so the model would mostly learn
        "which ticker is this" rather than anything about timing. Scaling by
        each name's own ATR makes a positive label mean the same thing
        everywhere: an unusually large move *for this stock*.

  ``label_up_5d``      -- is the forward 5-trading-day return positive?
        The plain directional question. Note the base rate is well above 50%
        because equities drift upward, so accuracy must always be read against
        that baseline, never against 50%.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

SPIKE_ATR_MULTIPLE = 2.0
DIRECTION_HORIZON = 5


def _forward_return(close: pd.Series, horizon: int) -> pd.Series:
    """Percent return from t to t+horizon.

    shift(-horizon) looks FORWARD, which is legitimate here and only here --
    this is the label. The final `horizon` rows become NaN because their
    outcome has not happened yet; they are the rows we predict on.
    """
    return (close.shift(-horizon) / close - 1) * 100


def _label_one_symbol(g: pd.DataFrame) -> pd.DataFrame:
    close = g["close"]
    out = pd.DataFrame(index=g.index)

    out["fwd_ret_1d"] = _forward_return(close, 1)
    out["fwd_ret_5d"] = _forward_return(close, DIRECTION_HORIZON)

    # ATR as a percentage of price, known at t. Using today's ATR to scale
    # tomorrow's move is the point: the threshold must be knowable in advance
    # or the label could not be acted on.
    atr_pct = g["_atr14"] / close.replace(0, np.nan) * 100
    threshold = SPIKE_ATR_MULTIPLE * atr_pct

    spike = out["fwd_ret_1d"] > threshold
    # Preserve NaN rather than letting a comparison against NaN silently
    # become False -- that would relabel "unknown outcome" as "no spike" and
    # quietly train the model on fabricated negatives.
    out["label_spike_2atr"] = spike.where(out["fwd_ret_1d"].notna() & threshold.notna())

    up = out["fwd_ret_5d"] > 0
    out["label_up_5d"] = up.where(out["fwd_ret_5d"].notna())

    out["_spike_threshold_pct"] = threshold
    return out


def add_labels(features: pd.DataFrame, bars: pd.DataFrame) -> pd.DataFrame:
    """Attach labels to a feature frame indexed by (symbol, date)."""
    if "_atr14" not in features.columns:
        raise ValueError("features must include _atr14 (from build_features)")

    indexed_bars = (
        bars.set_index(["symbol", "date"]).sort_index()
        if not isinstance(bars.index, pd.MultiIndex)
        else bars.sort_index()
    )
    joined = features.join(indexed_bars[["close"]], how="left")

    labels = (
        joined.groupby(level="symbol", group_keys=False, sort=False)
        .apply(_label_one_symbol)
    )
    return features.join(labels)


def label_columns() -> list[str]:
    return ["label_spike_2atr", "label_up_5d"]


def base_rates(frame: pd.DataFrame) -> dict[str, float]:
    """Positive-class rate for each label -- the number any model must beat.

    A classifier that always predicts the majority class scores exactly this.
    Reporting accuracy without it is how useless models look impressive.
    """
    out: dict[str, float] = {}
    for col in label_columns():
        if col in frame:
            s = frame[col].dropna()
            if len(s):
                out[col] = float(s.mean() * 100)
    return out
