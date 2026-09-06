"""Feature engineering for the forecasting models.

THE central invariant: a feature at date *t* may only use information
available at the close of *t*. Every rolling window here is trailing, every
shift is backwards, and nothing is centred. Violating this produces a model
that backtests beautifully and loses money live, which is the single most
common failure in applied finance ML.

Two guards make that checkable rather than aspirational:
  * every transform goes through a trailing rolling/ewm/shift, never
    ``center=True`` and never a negative shift;
  * ``tests/test_features.py`` asserts that appending future bars does not
    change already-computed feature values.

Input is long-format OHLCV with columns
``[symbol, date, open, high, low, close, volume]``.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from . import indicators as I

# Lookback windows for trailing returns, in trading days.
RETURN_WINDOWS = (1, 5, 10, 21, 63, 126, 252)

# The market context symbols whose behaviour is broadcast to every row.
MARKET_SYMBOL = "SPY"
VIX_SYMBOL = "^VIX"

# GICS sector name (as Wikipedia spells it) -> the SPDR sector ETF.
SECTOR_ETF: dict[str, str] = {
    "Information Technology": "XLK",
    "Financials": "XLF",
    "Health Care": "XLV",
    "Consumer Discretionary": "XLY",
    "Consumer Staples": "XLP",
    "Energy": "XLE",
    "Industrials": "XLI",
    "Materials": "XLB",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Communication Services": "XLC",
}

# "Days to next earnings" is capped here. Earnings dates are announced a few
# weeks ahead, so beyond ~30 calendar days a historical row would be using a
# date that was NOT yet public at the time -- mild lookahead. Capping treats
# everything past the horizon as "not soon", which is all the model needs and
# all a trader would have known.
EARNINGS_HORIZON_DAYS = 30


def _safe_div(a: pd.Series, b: pd.Series) -> pd.Series:
    return a / b.replace(0, np.nan)


def _rolling_beta(asset: pd.Series, bench: pd.Series, window: int = 60) -> pd.Series:
    """Rolling cov/var beta. indicators.beta() returns a single scalar for the
    latest window; the feature matrix needs one value per date."""
    a = I.log_returns(asset)
    b = I.log_returns(bench)
    joined = pd.concat([a, b], axis=1, join="inner").dropna()
    if joined.empty:
        return pd.Series(dtype=float)
    cov = joined.iloc[:, 0].rolling(window, min_periods=window // 2).cov(joined.iloc[:, 1])
    var = joined.iloc[:, 1].rolling(window, min_periods=window // 2).var()
    return cov / var.replace(0, np.nan)


def _per_symbol_features(g: pd.DataFrame) -> pd.DataFrame:
    """Features for one symbol. `g` is sorted ascending by date."""
    close, high, low, vol = g["close"], g["high"], g["low"], g["volume"]
    out = pd.DataFrame(index=g.index)

    # --- trend: price relative to its own moving averages --------------
    # Ratios, not raw levels: a $500 stock and a $5 stock must produce
    # comparable features or the model just learns price level.
    for w in (20, 50, 200):
        out[f"px_over_sma{w}"] = _safe_div(close, I.sma(close, w)) - 1
    out["sma20_over_sma50"] = _safe_div(I.sma(close, 20), I.sma(close, 50)) - 1
    out["sma50_over_sma200"] = _safe_div(I.sma(close, 50), I.sma(close, 200)) - 1

    # --- momentum -------------------------------------------------------
    for w in RETURN_WINDOWS:
        out[f"ret_{w}d"] = close.pct_change(w) * 100

    out["rsi_14"] = I.rsi(close, 14)
    out["rsi_5"] = I.rsi(close, 5)

    macd = I.macd(close)
    # Normalised by price so it is comparable across symbols.
    out["macd_hist_norm"] = _safe_div(macd["histogram"], close) * 100

    bb = I.bollinger(close, 20)
    out["bb_percent_b"] = bb["percent_b"]
    out["bb_bandwidth"] = bb["bandwidth"]

    # --- volatility -----------------------------------------------------
    for w in (10, 20, 60):
        out[f"vol_{w}d"] = I.realized_volatility(close, w)
    # Volatility expansion: short-term vol rising above long-term is a
    # classic precursor to large moves, which is exactly what the spike
    # label is trying to catch.
    out["vol_ratio_10_60"] = _safe_div(out["vol_10d"], out["vol_60d"])

    atr14 = I.atr(high, low, close, 14)
    out["atr_pct"] = _safe_div(atr14, close) * 100

    # --- price position / range -----------------------------------------
    day_range = (high - low).replace(0, np.nan)
    out["close_in_range"] = (close - low) / day_range
    out["gap_pct"] = _safe_div(g["open"] - close.shift(1), close.shift(1)) * 100

    roll_max = close.rolling(252, min_periods=60).max()
    roll_min = close.rolling(252, min_periods=60).min()
    out["pct_from_52w_high"] = (_safe_div(close, roll_max) - 1) * 100
    out["pct_from_52w_low"] = (_safe_div(close, roll_min) - 1) * 100
    out["drawdown_pct"] = (_safe_div(close, close.cummax()) - 1) * 100

    # --- trend strength / oscillators ------------------------------------
    out["adx_14"] = I.adx(high, low, close, 14)
    out["stoch_k_14"] = I.stochastic_k(high, low, close, 14)
    out["mfi_14"] = I.money_flow_index(high, low, close, vol, 14)
    out["obv_trend_20"] = I.obv_trend(close, vol, 20)

    # --- risk-adjusted return and distribution shape ---------------------
    out["downside_dev_60"] = I.downside_deviation(close, 60)
    out["sharpe_60"] = I.sharpe_ratio(close, 60)
    out["sortino_60"] = I.sortino_ratio(close, 60)
    out["ulcer_60"] = I.ulcer_index(close, 60)
    out["skew_120"] = I.return_skew(close, 120)
    out["kurtosis_120"] = I.return_kurtosis(close, 120)

    # --- volume ----------------------------------------------------------
    vol_mean20 = vol.rolling(20, min_periods=20).mean()
    vol_std20 = vol.rolling(20, min_periods=20).std(ddof=1)
    # shift(1) so today's own volume is excluded from its own baseline.
    out["volume_z"] = _safe_div(vol - vol_mean20.shift(1), vol_std20.shift(1))
    out["volume_ratio_5_20"] = _safe_div(vol.rolling(5).mean(), vol_mean20)
    out["dollar_volume_log"] = np.log1p(close * vol)

    # Internals for downstream consumers, underscore-prefixed so
    # feature_columns() excludes them. `close` in particular must NEVER be a
    # model feature -- the model would learn price level, which is meaningless
    # across a 529-symbol universe.
    out["_atr14"] = atr14
    out["_close"] = close
    return out


def _market_context(bars: pd.DataFrame) -> pd.DataFrame:
    """Market-wide series broadcast onto every symbol/date row."""
    wide_close = bars.pivot_table(index="date", columns="symbol", values="close")
    ctx = pd.DataFrame(index=wide_close.index)

    if MARKET_SYMBOL in wide_close:
        spy = wide_close[MARKET_SYMBOL]
        ctx["mkt_ret_1d"] = spy.pct_change(1) * 100
        ctx["mkt_ret_5d"] = spy.pct_change(5) * 100
        ctx["mkt_ret_21d"] = spy.pct_change(21) * 100
        ctx["mkt_vol_20d"] = I.realized_volatility(spy, 20)
        ctx["mkt_px_over_sma200"] = _safe_div(spy, I.sma(spy, 200)) - 1
        ctx["mkt_rsi_14"] = I.rsi(spy, 14)

    if VIX_SYMBOL in wide_close:
        vix = wide_close[VIX_SYMBOL]
        ctx["vix_level"] = vix
        ctx["vix_chg_5d"] = vix.pct_change(5) * 100
        # VIX relative to its own trailing average: "is fear elevated *for
        # this regime*" beats an absolute threshold that means different
        # things in 2017 and 2020.
        ctx["vix_over_sma20"] = _safe_div(vix, I.sma(vix, 20)) - 1

    return ctx


def _earnings_features(feats: pd.DataFrame, earnings: pd.DataFrame) -> pd.DataFrame:
    """days_to_earnings (capped) and days_since_earnings, via merge_asof.

    merge_asof(direction="forward") finds the next earnings date on or after
    each row's date; "backward" finds the most recent one before it. Both are
    O(n log n) rather than the O(n*m) a naive join would be.
    """
    if earnings is None or earnings.empty:
        feats["days_to_earnings"] = np.nan
        feats["days_since_earnings"] = np.nan
        feats["earnings_within_5d"] = np.nan
        return feats

    e = earnings.rename(columns={"earnings_date": "date"}).sort_values("date")
    e["_edate"] = e["date"]
    base = feats[["symbol", "date"]].sort_values("date")

    nxt = pd.merge_asof(base, e, on="date", by="symbol", direction="forward")
    prv = pd.merge_asof(base, e, on="date", by="symbol", direction="backward")

    to_next = (nxt["_edate"] - nxt["date"]).dt.days
    since = (prv["date"] - prv["_edate"]).dt.days

    to_next = to_next.clip(upper=EARNINGS_HORIZON_DAYS).fillna(EARNINGS_HORIZON_DAYS)
    nxt_frame = pd.DataFrame(
        {"symbol": nxt["symbol"], "date": nxt["date"],
         "days_to_earnings": to_next.to_numpy(),
         "earnings_within_5d": (to_next <= 5).astype(float).to_numpy()}
    )
    prv_frame = pd.DataFrame(
        {"symbol": prv["symbol"], "date": prv["date"], "days_since_earnings": since.to_numpy()}
    )
    feats = feats.merge(nxt_frame, on=["symbol", "date"], how="left")
    feats = feats.merge(prv_frame, on=["symbol", "date"], how="left")
    return feats


def _sector_relative(feats: pd.DataFrame, bars: pd.DataFrame, sector_map: dict[str, str]) -> pd.DataFrame:
    """Return minus the symbol's own sector ETF return.

    "Up 5% while the sector is up 6%" is a different fact from "up 5% while the
    sector is flat", and the market-relative feature cannot see it.
    """
    if not sector_map:
        return feats
    etfs = sorted(set(sector_map.values()))
    wide = bars[bars["symbol"].isin(etfs)].pivot_table(index="date", columns="symbol", values="close")
    if wide.empty:
        return feats

    sector_rets = {}
    for w in (5, 21):
        r = wide.pct_change(w) * 100
        sector_rets[w] = r.stack().rename(f"_sector_ret_{w}d").reset_index()
        sector_rets[w].columns = ["date", "_etf", f"_sector_ret_{w}d"]

    feats["_etf"] = feats["symbol"].map(sector_map)
    for w in (5, 21):
        feats = feats.merge(sector_rets[w], on=["date", "_etf"], how="left")
        feats[f"rel_sector_{w}d"] = feats[f"ret_{w}d"] - feats[f"_sector_ret_{w}d"]
        feats = feats.drop(columns=[f"_sector_ret_{w}d"])
    return feats.drop(columns=["_etf"])


def build_features(
    bars: pd.DataFrame,
    earnings: pd.DataFrame | None = None,
    sector_map: dict[str, str] | None = None,
) -> pd.DataFrame:
    """Long-format OHLCV -> feature matrix indexed by (symbol, date).

    `earnings` is a (symbol, earnings_date) frame; `sector_map` maps a symbol
    to its sector ETF. Both optional so the pure-bars path still works.

    Rows are NOT dropped here even when features are NaN during the warm-up
    period; dropping is the caller's decision, because the prediction path
    wants the most recent row even if some long-window feature is missing.
    """
    required = {"symbol", "date", "open", "high", "low", "close", "volume"}
    missing = required - set(bars.columns)
    if missing:
        raise ValueError(f"bars is missing columns: {sorted(missing)}")

    bars = bars.sort_values(["symbol", "date"]).reset_index(drop=True)

    per_symbol = (
        bars.groupby("symbol", group_keys=False, sort=False)
        .apply(_per_symbol_features, include_groups=False)
    )
    feats = pd.concat([bars[["symbol", "date"]], per_symbol], axis=1)

    ctx = _market_context(bars)
    if not ctx.empty:
        feats = feats.merge(ctx, left_on="date", right_index=True, how="left")

    # --- cross-sectional ranks -------------------------------------------
    # Computed within a single date across symbols, so no future information
    # is involved. Percentile ranks make "strongest name today" a feature
    # that is stable across market regimes.
    for col in ("ret_5d", "ret_21d", "ret_126d", "volume_z", "vol_20d"):
        if col in feats:
            feats[f"xs_rank_{col}"] = feats.groupby("date")[col].rank(pct=True)

    # --- benchmark-relative risk -----------------------------------------
    # Beta and correlation need two series, so they cannot be computed in the
    # per-symbol pass. Both align on shared dates first: crypto trades weekends
    # and equities do not, and an unaligned join silently pairs a Saturday
    # crypto move against Friday's equity move.
    wide_close = bars.pivot_table(index="date", columns="symbol", values="close")
    if MARKET_SYMBOL in wide_close:
        bench = wide_close[MARKET_SYMBOL]
        beta_frames, corr_frames = [], []
        for symbol in wide_close.columns:
            series = wide_close[symbol].dropna()
            if len(series) < 80:
                continue
            corr = I.rolling_correlation(series, bench, 60)
            beta_series = _rolling_beta(series, bench, 60)
            corr_frames.append(pd.DataFrame({"symbol": symbol, "date": corr.index, "corr_spy_60": corr.to_numpy()}))
            beta_frames.append(pd.DataFrame({"symbol": symbol, "date": beta_series.index, "beta_60": beta_series.to_numpy()}))
        if corr_frames:
            feats = feats.merge(pd.concat(corr_frames, ignore_index=True), on=["symbol", "date"], how="left")
        if beta_frames:
            feats = feats.merge(pd.concat(beta_frames, ignore_index=True), on=["symbol", "date"], how="left")

    # Relative strength vs the market over the same window.
    if "mkt_ret_21d" in feats:
        feats["rel_strength_21d"] = feats["ret_21d"] - feats["mkt_ret_21d"]
    if "mkt_ret_5d" in feats:
        feats["rel_strength_5d"] = feats["ret_5d"] - feats["mkt_ret_5d"]

    feats = _sector_relative(feats, bars, sector_map or {})
    feats = _earnings_features(feats, earnings)

    # float32 for model inputs: a million rows x ~60 features is ~500MB in
    # float64 and ~250MB in float32, and every sklearn copy doubles that. No
    # indicator here needs more than ~7 significant figures. Internals
    # (underscore-prefixed) stay float64 because the labeller compares against
    # them and a boundary case must not flip on a cast.
    feature_cols = [
        c for c in feats.columns
        if c not in ("symbol", "date") and not c.startswith("_")
        and pd.api.types.is_float_dtype(feats[c])
    ]
    feats[feature_cols] = feats[feature_cols].astype("float32")

    return feats.set_index(["symbol", "date"]).sort_index()


def feature_columns(frame: pd.DataFrame) -> list[str]:
    """Model input columns: everything except internals and labels."""
    return [
        c
        for c in frame.columns
        if not c.startswith("_") and not c.startswith("label_") and not c.startswith("fwd_")
    ]
