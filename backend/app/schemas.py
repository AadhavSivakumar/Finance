"""API request/response models.

Decimals are serialized as strings so no precision is lost in JSON; computed
analytics are plain floats, because an RSI of 54.3 does not need 28 digits and
float keeps the payloads small.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------
# Market data primitives (used by services/prices.py)
# --------------------------------------------------------------------------


class Quote(BaseModel):
    symbol: str
    price: Decimal
    change: Decimal
    change_pct: Decimal
    currency: str = "USD"
    as_of: date


class Candle(BaseModel):
    date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal


# --------------------------------------------------------------------------
# Reference
# --------------------------------------------------------------------------


class InstrumentOut(ORMModel):
    symbol: str
    name: str
    asset_group: str
    sector: str
    short_label: str
    universe: str


# --------------------------------------------------------------------------
# Analytics
# --------------------------------------------------------------------------


class SnapshotOut(ORMModel):
    symbol: str
    as_of: date
    close: float | None = None
    ret_1d: float | None = None
    ret_5d: float | None = None
    ret_21d: float | None = None
    ret_63d: float | None = None
    ret_252d: float | None = None
    rsi_14: float | None = None
    vol_20d: float | None = None
    vol_ratio_10_60: float | None = None
    atr_pct: float | None = None
    pct_from_52w_high: float | None = None
    drawdown_pct: float | None = None
    volume_z: float | None = None
    rel_strength_21d: float | None = None
    px_over_sma200: float | None = None


class MoverRow(BaseModel):
    """A snapshot decorated with display metadata, for ranking tables."""

    symbol: str
    name: str
    short_label: str
    asset_group: str
    sector: str
    close: float | None = None
    ret_1d: float | None = None
    ret_5d: float | None = None
    ret_21d: float | None = None
    ret_63d: float | None = None
    ret_252d: float | None = None
    rsi_14: float | None = None
    vol_20d: float | None = None
    volume_z: float | None = None
    rel_strength_21d: float | None = None
    pct_from_52w_high: float | None = None


class RegimeOut(BaseModel):
    """The one-glance read on market state."""

    as_of: date
    trend: str                       # risk-on | risk-off | mixed
    breadth_pct: float               # % of universe above its 200d SMA
    advancers_pct: float             # % up on the day
    spy_px_over_sma200: float | None = None
    vix_level: float | None = None
    vix_percentile_1y: float | None = None
    avg_correlation: float | None = None
    notes: list[str] = []


class SignalOut(ORMModel):
    symbol: str
    as_of: date
    kind: str
    direction: str
    strength: float | None = None
    detail: str


class CorrelationOut(BaseModel):
    as_of: date
    window: int
    symbols: list[str]
    labels: list[str]
    matrix: list[list[float | None]]


class PredictionOut(BaseModel):
    # Pydantic v2 reserves the "model_" prefix; these fields are named that way
    # deliberately (they describe the model, not the prediction), so the
    # namespace guard is switched off rather than the names mangled.
    model_config = ConfigDict(protected_namespaces=())

    symbol: str
    name: str
    as_of: date
    target: str
    model: str
    probability: float
    percentile: float | None = None
    # Repeated from the model run so a caller cannot read a probability
    # without also seeing whether the model has any measured edge.
    model_roc_auc: float | None = None
    model_lift: float | None = None
    model_edge_vs_baseline: float | None = None


class ModelRunOut(ORMModel):
    target: str
    model: str
    trained_at: datetime
    n_train: int
    n_features: int
    train_start: date | None = None
    train_end: date | None = None
    roc_auc: float | None = None
    base_rate: float | None = None
    accuracy: float | None = None
    baseline_accuracy: float | None = None
    edge_vs_baseline: float | None = None
    top_decile_precision: float | None = None
    lift: float | None = None
    is_active: bool = False
    metrics: dict[str, Any] = {}


class MacroPoint(BaseModel):
    date: date
    value: float | None = None


class MacroSeriesOut(BaseModel):
    series_id: str
    title: str
    units: str
    category: str
    latest_value: float | None = None
    latest_date: date | None = None
    change_1y: float | None = None
    points: list[MacroPoint] = []


class ComputeRunOut(ORMModel):
    kind: str
    status: str
    started_at: datetime
    finished_at: datetime | None = None
    duration_seconds: float | None = None
    detail: dict[str, Any] = {}
    error: str = ""


class HistoryPoint(BaseModel):
    date: date
    close: float
