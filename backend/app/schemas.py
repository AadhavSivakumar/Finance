from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from .models import AssetClass, Interval, TxnType


class ORMModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


# --------------------------------------------------------------------------
# Portfolio
# --------------------------------------------------------------------------


class PortfolioCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    base_currency: str = Field(default="USD", min_length=3, max_length=3)


class PortfolioOut(ORMModel):
    id: int
    name: str
    base_currency: str


class TransactionCreate(BaseModel):
    symbol: str = Field(min_length=1, max_length=24)
    type: TxnType
    quantity: Decimal = Field(gt=0)
    price: Decimal = Field(ge=0)
    fee: Decimal = Field(default=Decimal("0"), ge=0)
    executed_at: date
    note: str = ""

    @field_validator("symbol")
    @classmethod
    def upper(cls, v: str) -> str:
        return v.strip().upper()


class TransactionOut(ORMModel):
    id: int
    portfolio_id: int
    symbol: str
    type: TxnType
    quantity: Decimal
    price: Decimal
    fee: Decimal
    executed_at: date
    note: str


class HoldingOut(BaseModel):
    symbol: str
    name: str = ""
    asset_class: AssetClass = AssetClass.equity
    quantity: Decimal
    avg_cost: Decimal
    cost_basis: Decimal
    last_price: Decimal
    market_value: Decimal
    unrealized_pl: Decimal
    unrealized_pl_pct: Decimal
    weight_pct: Decimal
    # False when no live quote was available and the position is valued at
    # average cost instead.
    has_quote: bool = True


class PortfolioSummary(BaseModel):
    portfolio_id: int
    name: str
    base_currency: str
    market_value: Decimal
    cost_basis: Decimal
    unrealized_pl: Decimal
    unrealized_pl_pct: Decimal
    realized_pl: Decimal
    dividend_income: Decimal
    holdings: list[HoldingOut]


class AllocationSlice(BaseModel):
    key: str
    market_value: Decimal
    weight_pct: Decimal


class PerformancePoint(BaseModel):
    date: date
    market_value: Decimal
    cost_basis: Decimal


# --------------------------------------------------------------------------
# Market data
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


class WatchlistCreate(BaseModel):
    symbol: str = Field(min_length=1, max_length=24)
    note: str = ""

    @field_validator("symbol")
    @classmethod
    def upper(cls, v: str) -> str:
        return v.strip().upper()


class WatchlistOut(ORMModel):
    id: int
    symbol: str
    note: str


# --------------------------------------------------------------------------
# Business metrics
# --------------------------------------------------------------------------


class RevenueStreamCreate(BaseModel):
    name: str = Field(min_length=1, max_length=160)
    customer: str = ""
    interval: Interval = Interval.monthly
    amount: Decimal = Field(ge=0)
    currency: str = "USD"
    start_date: date
    end_date: date | None = None


class RevenueStreamOut(ORMModel):
    id: int
    name: str
    customer: str
    interval: Interval
    amount: Decimal
    currency: str
    start_date: date
    end_date: date | None


class ExpenseCreate(BaseModel):
    category: str = Field(min_length=1, max_length=80)
    vendor: str = ""
    interval: Interval = Interval.monthly
    amount: Decimal = Field(ge=0)
    currency: str = "USD"
    start_date: date
    end_date: date | None = None


class ExpenseOut(ORMModel):
    id: int
    category: str
    vendor: str
    interval: Interval
    amount: Decimal
    currency: str
    start_date: date
    end_date: date | None


class CashSnapshotCreate(BaseModel):
    as_of: date
    amount: Decimal
    currency: str = "USD"


class CashSnapshotOut(ORMModel):
    id: int
    as_of: date
    amount: Decimal
    currency: str


class MonthlyPoint(BaseModel):
    month: str  # YYYY-MM
    revenue: Decimal
    mrr: Decimal
    expenses: Decimal
    net: Decimal


class BusinessSummary(BaseModel):
    as_of: date
    mrr: Decimal
    arr: Decimal
    monthly_expenses: Decimal
    net_burn: Decimal
    gross_margin_pct: Decimal
    cash: Decimal
    runway_months: Decimal | None  # None == profitable / infinite runway
    mom_revenue_growth_pct: Decimal
    series: list[MonthlyPoint]


class ExpenseBreakdown(BaseModel):
    category: str
    monthly_amount: Decimal
    share_pct: Decimal
