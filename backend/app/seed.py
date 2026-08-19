"""Populate the database with a realistic demo dataset.

Run with ``docker compose exec api python -m app.seed``. Idempotent: it does
nothing if a portfolio already exists, so it is safe to wire into a startup
script.
"""

from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from sqlalchemy import select

from .db import SessionLocal
from .models import (
    AssetClass,
    CashSnapshot,
    Expense,
    Instrument,
    Interval,
    Portfolio,
    RevenueStream,
    Transaction,
    TxnType,
    WatchlistItem,
)

log = logging.getLogger(__name__)

INSTRUMENTS = [
    ("AAPL", "Apple Inc.", AssetClass.equity),
    ("MSFT", "Microsoft Corp.", AssetClass.equity),
    ("NVDA", "NVIDIA Corp.", AssetClass.equity),
    ("VTI", "Vanguard Total Stock Market ETF", AssetClass.etf),
    ("VXUS", "Vanguard Total International Stock ETF", AssetClass.etf),
    ("BND", "Vanguard Total Bond Market ETF", AssetClass.etf),
    ("BTC-USD", "Bitcoin", AssetClass.crypto),
    ("ETH-USD", "Ethereum", AssetClass.crypto),
]

# (symbol, months_ago, quantity, price)
TRADES = [
    ("VTI", 30, "40", "210.50"),
    ("VTI", 18, "25", "228.10"),
    ("VXUS", 28, "60", "56.20"),
    ("BND", 26, "80", "72.40"),
    ("AAPL", 24, "30", "168.90"),
    ("AAPL", 9, "15", "196.40"),
    ("MSFT", 22, "18", "310.75"),
    ("NVDA", 20, "24", "128.60"),
    ("BTC-USD", 16, "0.35", "41250.00"),
    ("ETH-USD", 14, "3.2", "2380.00"),
]

SELLS = [("NVDA", 4, "6", "172.30")]
DIVIDENDS = [("VTI", 3, "65", "0.94"), ("BND", 3, "80", "0.19")]

# (name, customer, interval, amount, starts_months_ago, ends_months_ago | None)
#
# Deliberately staggered. A dataset where every stream starts 24 months ago at
# a fixed amount produces a perfectly flat MRR chart and 0% growth -- correct
# arithmetic over boring data, which demos nothing. Cohorts land at intervals,
# one account churns, and enterprise contracts sign over time.
REVENUE = [
    # Annual enterprise contracts (recognized at amount/12 per month).
    ("Enterprise - Northwind", "Northwind Corp", Interval.annual, "96000", 20, None),
    ("Enterprise - Contoso", "Contoso Ltd", Interval.annual, "72000", 14, None),
    ("Enterprise - Fabrikam", "Fabrikam Inc", Interval.annual, "60000", 5, None),
    ("Enterprise - Tailspin", "Tailspin Toys", Interval.annual, "48000", 2, None),
    # Self-serve cohorts, added over time.
    ("Team plan - 2024 cohort", "SMB self-serve", Interval.monthly, "6200", 24, None),
    ("Team plan - H1 cohort", "SMB self-serve", Interval.monthly, "4800", 15, None),
    ("Team plan - H2 cohort", "SMB self-serve", Interval.monthly, "5400", 9, None),
    ("Team plan - Q2 cohort", "SMB self-serve", Interval.monthly, "3900", 4, None),
    ("Pro plan - early", "Self-serve", Interval.monthly, "4100", 22, None),
    ("Pro plan - growth", "Self-serve", Interval.monthly, "3300", 11, None),
    ("Pro plan - recent", "Self-serve", Interval.monthly, "2600", 3, None),
    # A churned account, so the MRR line has a visible dip to explain.
    ("Design partner - Contoso", "Contoso Ltd", Interval.monthly, "3500", 21, 7),
    # One-time services: spikes in revenue that must NOT move MRR.
    ("Onboarding - Northwind", "Northwind Corp", Interval.one_time, "15000", 19, None),
    ("Onboarding - Fabrikam", "Fabrikam Inc", Interval.one_time, "12000", 5, None),
    ("Migration services", "Contoso Ltd", Interval.one_time, "9000", 1, None),
]

# (category, vendor, interval, amount, starts_months_ago, ends_months_ago | None)
#
# Payroll and hosting step up as the company grows. Each step ends the month
# before the next begins, so no month double-counts and none has a gap.
EXPENSES = [
    ("Payroll", "Gusto", Interval.monthly, "52000", 24, 13),
    ("Payroll", "Gusto", Interval.monthly, "71000", 12, 6),
    ("Payroll", "Gusto", Interval.monthly, "88000", 5, None),
    ("Hosting", "AWS", Interval.monthly, "6400", 24, 11),
    ("Hosting", "AWS", Interval.monthly, "11200", 10, None),
    ("Infrastructure", "Datadog", Interval.monthly, "2400", 20, None),
    ("Payment processing", "Stripe", Interval.monthly, "1850", 24, None),
    ("Marketing", "Various", Interval.monthly, "7500", 16, None),
    ("Software", "SaaS tools", Interval.monthly, "3100", 24, None),
    ("Office & G&A", "Various", Interval.monthly, "4200", 24, None),
    ("Legal", "Counsel", Interval.annual, "36000", 18, None),
]


def seed() -> None:
    db = SessionLocal()
    try:
        if db.scalar(select(Portfolio).limit(1)) is not None:
            log.info("database already seeded, skipping")
            return

        today = date.today()

        for symbol, name, cls in INSTRUMENTS:
            db.add(Instrument(symbol=symbol, name=name, asset_class=cls))

        portfolio = Portfolio(name="Main Portfolio", base_currency="USD")
        db.add(portfolio)
        db.flush()

        def months_ago(n: int) -> date:
            return today - relativedelta(months=n)

        for symbol, ago, qty, price in TRADES:
            db.add(
                Transaction(
                    portfolio_id=portfolio.id,
                    symbol=symbol,
                    type=TxnType.buy,
                    quantity=Decimal(qty),
                    price=Decimal(price),
                    fee=Decimal("1.00"),
                    executed_at=months_ago(ago),
                )
            )
        for symbol, ago, qty, price in SELLS:
            db.add(
                Transaction(
                    portfolio_id=portfolio.id,
                    symbol=symbol,
                    type=TxnType.sell,
                    quantity=Decimal(qty),
                    price=Decimal(price),
                    fee=Decimal("1.00"),
                    executed_at=months_ago(ago),
                    note="Trimmed position",
                )
            )
        for symbol, ago, qty, price in DIVIDENDS:
            db.add(
                Transaction(
                    portfolio_id=portfolio.id,
                    symbol=symbol,
                    type=TxnType.dividend,
                    quantity=Decimal(qty),
                    price=Decimal(price),
                    executed_at=months_ago(ago),
                    note="Quarterly distribution",
                )
            )

        for symbol in ("NVDA", "MSFT", "BTC-USD"):
            db.add(WatchlistItem(symbol=symbol, note="Watching for entry"))

        for name, customer, interval, amount, start_ago, end_ago in REVENUE:
            db.add(
                RevenueStream(
                    name=name,
                    customer=customer,
                    interval=interval,
                    amount=Decimal(amount),
                    start_date=months_ago(start_ago),
                    end_date=months_ago(end_ago) if end_ago is not None else None,
                )
            )

        for category, vendor, interval, amount, start_ago, end_ago in EXPENSES:
            db.add(
                Expense(
                    category=category,
                    vendor=vendor,
                    interval=interval,
                    amount=Decimal(amount),
                    start_date=months_ago(start_ago),
                    end_date=months_ago(end_ago) if end_ago is not None else None,
                )
            )

        # Six months of cash balances, declining with the burn. The most recent
        # one is what runway divides by net burn.
        for i, amount in enumerate(
            ["1607000", "1533000", "1455000", "1382000", "1311000", "1244000"]
        ):
            db.add(
                CashSnapshot(as_of=months_ago(5 - i).replace(day=1), amount=Decimal(amount))
            )

        db.commit()
        log.info("seeded demo dataset")
    finally:
        db.close()


if __name__ == "__main__":
    logging.basicConfig(level="INFO", format="%(levelname)s %(message)s")
    seed()
