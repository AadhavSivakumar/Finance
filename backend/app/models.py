from __future__ import annotations

import enum
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import (
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

# Money is Numeric, never float: binary floats cannot represent 0.10 exactly and
# the error compounds across thousands of rows.
Money = Numeric(18, 2)
Qty = Numeric(24, 8)
Price = Numeric(18, 6)


class TxnType(str, enum.Enum):
    buy = "buy"
    sell = "sell"
    dividend = "dividend"


class AssetClass(str, enum.Enum):
    equity = "equity"
    etf = "etf"
    crypto = "crypto"
    cash = "cash"
    other = "other"


class Interval(str, enum.Enum):
    monthly = "monthly"
    annual = "annual"
    one_time = "one_time"


# --------------------------------------------------------------------------
# Portfolio / market side
# --------------------------------------------------------------------------


class Portfolio(Base):
    __tablename__ = "portfolios"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    base_currency: Mapped[str] = mapped_column(String(3), default="USD")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    transactions: Mapped[list[Transaction]] = relationship(
        back_populates="portfolio", cascade="all, delete-orphan"
    )


class Instrument(Base):
    """Symbol metadata cache, so we do not re-fetch a name on every request."""

    __tablename__ = "instruments"

    symbol: Mapped[str] = mapped_column(String(24), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), default="")
    asset_class: Mapped[AssetClass] = mapped_column(
        Enum(AssetClass, name="asset_class"), default=AssetClass.equity
    )
    currency: Mapped[str] = mapped_column(String(3), default="USD")


class Transaction(Base):
    """Holdings are *derived* from transactions rather than stored.

    Storing a mutable quantity alongside the trades that produced it is how
    portfolios drift out of balance; one source of truth avoids that.
    """

    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(primary_key=True)
    portfolio_id: Mapped[int] = mapped_column(
        ForeignKey("portfolios.id", ondelete="CASCADE"), index=True
    )
    symbol: Mapped[str] = mapped_column(String(24), index=True)
    type: Mapped[TxnType] = mapped_column(Enum(TxnType, name="txn_type"))
    quantity: Mapped[Decimal] = mapped_column(Qty)
    price: Mapped[Decimal] = mapped_column(Price)
    fee: Mapped[Decimal] = mapped_column(Money, default=Decimal("0"))
    executed_at: Mapped[date] = mapped_column(Date, index=True)
    note: Mapped[str] = mapped_column(Text, default="")

    portfolio: Mapped[Portfolio] = relationship(back_populates="transactions")


class PriceBar(Base):
    """Daily OHLC cache. Keeps chart requests off the upstream provider."""

    __tablename__ = "price_bars"
    __table_args__ = (
        UniqueConstraint("symbol", "bar_date", name="uq_price_bars_symbol_date"),
        Index("ix_price_bars_symbol_date", "symbol", "bar_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(24))
    bar_date: Mapped[date] = mapped_column(Date)
    open: Mapped[Decimal] = mapped_column(Price)
    high: Mapped[Decimal] = mapped_column(Price)
    low: Mapped[Decimal] = mapped_column(Price)
    close: Mapped[Decimal] = mapped_column(Price)
    volume: Mapped[Decimal] = mapped_column(Numeric(24, 2), default=Decimal("0"))


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    symbol: Mapped[str] = mapped_column(String(24), unique=True)
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


# --------------------------------------------------------------------------
# Business metrics side
# --------------------------------------------------------------------------


class RevenueStream(Base):
    """A contract or product line. Recurring rows drive MRR; one-time rows do not."""

    __tablename__ = "revenue_streams"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    customer: Mapped[str] = mapped_column(String(160), default="")
    interval: Mapped[Interval] = mapped_column(
        Enum(Interval, name="revenue_interval"), default=Interval.monthly
    )
    amount: Mapped[Decimal] = mapped_column(Money)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    start_date: Mapped[date] = mapped_column(Date, index=True)
    # NULL end_date means still active.
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)


class Expense(Base):
    __tablename__ = "expenses"

    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[str] = mapped_column(String(80), index=True)
    vendor: Mapped[str] = mapped_column(String(160), default="")
    interval: Mapped[Interval] = mapped_column(
        Enum(Interval, name="expense_interval"), default=Interval.monthly
    )
    amount: Mapped[Decimal] = mapped_column(Money)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
    start_date: Mapped[date] = mapped_column(Date, index=True)
    end_date: Mapped[date | None] = mapped_column(Date, nullable=True)


class CashSnapshot(Base):
    """Bank balance at a point in time. Runway = latest balance / net burn."""

    __tablename__ = "cash_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True)
    as_of: Mapped[date] = mapped_column(Date, unique=True)
    amount: Mapped[Decimal] = mapped_column(Money)
    currency: Mapped[str] = mapped_column(String(3), default="USD")
