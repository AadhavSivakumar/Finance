"""Database schema for the market analytics dashboard.

Nothing here models a user's holdings. Every table describes the *market* or
the model's opinion about it, which is the whole point of the rebuild.

Two storage decisions worth stating:

* Money/prices are ``Numeric``, never float. Binary floats cannot represent
  0.10 exactly and the error compounds across millions of bars.
* The long tail of computed metrics lives in a JSONB ``extras`` column rather
  than 40 typed columns. The metrics we sort and filter by are typed and
  indexed; the rest ride along as JSON so adding an indicator does not require
  a migration.
"""

from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from .db import Base

Price = Numeric(18, 6)
Volume = Numeric(24, 2)

# JSONB on Postgres, plain JSON elsewhere (the test suite uses SQLite).
JSONType = JSON().with_variant(JSONB(), "postgresql")


class AssetGroup(str, enum.Enum):
    index = "index"
    sector = "sector"
    bond = "bond"
    commodity = "commodity"
    crypto = "crypto"
    volatility = "volatility"
    equity = "equity"


class RunStatus(str, enum.Enum):
    running = "running"
    success = "success"
    failed = "failed"


# --------------------------------------------------------------------------
# Reference data
# --------------------------------------------------------------------------


class Instrument(Base):
    __tablename__ = "instruments"

    symbol: Mapped[str] = mapped_column(String(24), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    # Named asset_group, not "group": GROUP is a reserved SQL word and any raw
    # query would need quoting forever after.
    asset_group: Mapped[AssetGroup] = mapped_column(
        Enum(AssetGroup, name="asset_group"), default=AssetGroup.equity, index=True
    )
    # GICS sector for single stocks; empty for ETFs and crypto.
    sector: Mapped[str] = mapped_column(String(80), default="", index=True)
    short_label: Mapped[str] = mapped_column(String(40), default="")
    # "context" = the fixed macro/sector universe, "sp500" = constituents.
    universe: Mapped[str] = mapped_column(String(24), default="context", index=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    added_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class PriceBar(Base):
    """Daily OHLCV. The local cache that makes a 500-symbol universe viable:
    the worker fetches only bars newer than the newest stored one."""

    __tablename__ = "price_bars"
    __table_args__ = (
        UniqueConstraint("symbol", "bar_date", name="uq_price_bars_symbol_date"),
        Index("ix_price_bars_symbol_date", "symbol", "bar_date"),
        Index("ix_price_bars_date", "bar_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(24), nullable=False)
    bar_date: Mapped[date] = mapped_column(Date, nullable=False)
    open: Mapped[Decimal] = mapped_column(Price)
    high: Mapped[Decimal] = mapped_column(Price)
    low: Mapped[Decimal] = mapped_column(Price)
    close: Mapped[Decimal] = mapped_column(Price)
    volume: Mapped[Decimal] = mapped_column(Volume, default=Decimal("0"))


# --------------------------------------------------------------------------
# Computed analytics
# --------------------------------------------------------------------------


class Snapshot(Base):
    """Latest computed metrics for one symbol on one date."""

    __tablename__ = "snapshots"
    __table_args__ = (
        UniqueConstraint("symbol", "as_of", name="uq_snapshots_symbol_date"),
        Index("ix_snapshots_as_of", "as_of"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(24), index=True)
    as_of: Mapped[date] = mapped_column(Date)

    close: Mapped[float | None] = mapped_column(Float)
    ret_1d: Mapped[float | None] = mapped_column(Float)
    ret_5d: Mapped[float | None] = mapped_column(Float)
    ret_21d: Mapped[float | None] = mapped_column(Float)
    ret_63d: Mapped[float | None] = mapped_column(Float)
    ret_252d: Mapped[float | None] = mapped_column(Float)
    rsi_14: Mapped[float | None] = mapped_column(Float)
    vol_20d: Mapped[float | None] = mapped_column(Float)
    vol_ratio_10_60: Mapped[float | None] = mapped_column(Float)
    atr_pct: Mapped[float | None] = mapped_column(Float)
    pct_from_52w_high: Mapped[float | None] = mapped_column(Float)
    drawdown_pct: Mapped[float | None] = mapped_column(Float)
    volume_z: Mapped[float | None] = mapped_column(Float)
    rel_strength_21d: Mapped[float | None] = mapped_column(Float)
    px_over_sma200: Mapped[float | None] = mapped_column(Float)

    extras: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)


class Prediction(Base):
    """A model's probability for one symbol/target/date.

    `percentile` is the cross-sectional rank on that date. Ranking is how the
    predictions are actually consumed -- "today's top 10 candidates" -- and it
    is far more robust than an absolute probability threshold, which drifts as
    the model is retrained.
    """

    __tablename__ = "predictions"
    __table_args__ = (
        UniqueConstraint(
            "symbol", "as_of", "target", "model", name="uq_predictions_key"
        ),
        Index("ix_predictions_asof_target", "as_of", "target"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(24), index=True)
    as_of: Mapped[date] = mapped_column(Date)
    target: Mapped[str] = mapped_column(String(40))
    model: Mapped[str] = mapped_column(String(40))
    probability: Mapped[float] = mapped_column(Float)
    percentile: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class ModelRun(Base):
    """Provenance and out-of-sample scores for one trained model.

    The metrics blob carries the walk-forward results, including the baseline
    each model must beat. Storing it means the UI can display "this model has
    no edge" rather than silently presenting its predictions as meaningful.
    """

    __tablename__ = "model_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    target: Mapped[str] = mapped_column(String(40), index=True)
    model: Mapped[str] = mapped_column(String(40))
    trained_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    n_train: Mapped[int] = mapped_column(Integer, default=0)
    n_features: Mapped[int] = mapped_column(Integer, default=0)
    train_start: Mapped[date | None] = mapped_column(Date)
    train_end: Mapped[date | None] = mapped_column(Date)

    roc_auc: Mapped[float | None] = mapped_column(Float)
    base_rate: Mapped[float | None] = mapped_column(Float)
    accuracy: Mapped[float | None] = mapped_column(Float)
    baseline_accuracy: Mapped[float | None] = mapped_column(Float)
    edge_vs_baseline: Mapped[float | None] = mapped_column(Float)
    top_decile_precision: Mapped[float | None] = mapped_column(Float)
    lift: Mapped[float | None] = mapped_column(Float)

    metrics: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)


class Signal(Base):
    """A discrete, explainable event -- the feed a human actually reads."""

    __tablename__ = "signals"
    __table_args__ = (
        UniqueConstraint("symbol", "as_of", "kind", name="uq_signals_key"),
        Index("ix_signals_asof", "as_of"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(24), index=True)
    as_of: Mapped[date] = mapped_column(Date)
    kind: Mapped[str] = mapped_column(String(60))
    direction: Mapped[str] = mapped_column(String(10), default="neutral")
    strength: Mapped[float | None] = mapped_column(Float)
    detail: Mapped[str] = mapped_column(Text, default="")


class CorrelationSnapshot(Base):
    """Full pairwise matrix for one date, stored whole.

    N^2/2 rows per date would be ~340k rows for 26 symbols over a year, all to
    serve one heatmap. One JSON document per date is the right shape here.
    """

    __tablename__ = "correlation_snapshots"
    __table_args__ = (
        UniqueConstraint("as_of", "window", name="uq_correlation_key"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    as_of: Mapped[date] = mapped_column(Date, index=True)
    window: Mapped[int] = mapped_column(Integer, default=90)
    symbols: Mapped[list[str]] = mapped_column(JSONType, default=list)
    matrix: Mapped[list[list[float]]] = mapped_column(JSONType, default=list)


class MacroSeries(Base):
    __tablename__ = "macro_series"

    series_id: Mapped[str] = mapped_column(String(40), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), default="")
    units: Mapped[str] = mapped_column(String(80), default="")
    category: Mapped[str] = mapped_column(String(40), default="", index=True)


class MacroObservation(Base):
    __tablename__ = "macro_observations"
    __table_args__ = (
        UniqueConstraint("series_id", "obs_date", name="uq_macro_obs"),
        Index("ix_macro_obs_series_date", "series_id", "obs_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    series_id: Mapped[str] = mapped_column(
        String(40), ForeignKey("macro_series.series_id", ondelete="CASCADE")
    )
    obs_date: Mapped[date] = mapped_column(Date)
    value: Mapped[float | None] = mapped_column(Float)


class ComputeRun(Base):
    """One worker cycle. Makes 'is the data stale?' answerable in the UI."""

    __tablename__ = "compute_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(String(40), index=True)
    status: Mapped[RunStatus] = mapped_column(
        Enum(RunStatus, name="run_status"), default=RunStatus.running
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duration_seconds: Mapped[float | None] = mapped_column(Float)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONType, default=dict)
    error: Mapped[str] = mapped_column(Text, default="")
