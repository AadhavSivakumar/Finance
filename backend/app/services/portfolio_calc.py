"""Derive holdings, P&L and performance series from the transaction log.

Cost basis uses the **average cost** method (the default for most brokers
outside the US and the simplest defensible choice here). Switching to FIFO
would mean keeping a per-lot queue instead of a running average; the seam for
that is ``_replay``.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Instrument, Portfolio, Transaction, TxnType
from ..schemas import (
    AllocationSlice,
    HoldingOut,
    PerformancePoint,
    PortfolioSummary,
)
from . import prices

ZERO = Decimal("0")


def _pct(part: Decimal, whole: Decimal) -> Decimal:
    if whole == ZERO:
        return ZERO
    return (part / whole * 100).quantize(Decimal("0.01"))


def _money(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"))


@dataclass
class Position:
    symbol: str
    quantity: Decimal = ZERO
    cost_basis: Decimal = ZERO
    realized_pl: Decimal = ZERO
    dividends: Decimal = ZERO

    @property
    def avg_cost(self) -> Decimal:
        if self.quantity == ZERO:
            return ZERO
        return self.cost_basis / self.quantity


def _replay(txns: list[Transaction]) -> dict[str, Position]:
    """Fold the transaction log into current positions."""
    positions: dict[str, Position] = defaultdict(lambda: Position(symbol=""))
    for txn in sorted(txns, key=lambda t: (t.executed_at, t.id)):
        pos = positions[txn.symbol]
        pos.symbol = txn.symbol

        if txn.type is TxnType.buy:
            pos.quantity += txn.quantity
            pos.cost_basis += txn.quantity * txn.price + txn.fee

        elif txn.type is TxnType.sell:
            # Selling more than held is a data error; clamp so one bad row
            # cannot poison every downstream number.
            sold = min(txn.quantity, pos.quantity)
            avg = pos.avg_cost
            pos.realized_pl += sold * (txn.price - avg) - txn.fee
            pos.cost_basis -= sold * avg
            pos.quantity -= sold

        elif txn.type is TxnType.dividend:
            pos.dividends += txn.quantity * txn.price

    return dict(positions)


def _instrument_map(db: Session, symbols: list[str]) -> dict[str, Instrument]:
    if not symbols:
        return {}
    rows = db.scalars(select(Instrument).where(Instrument.symbol.in_(symbols))).all()
    return {r.symbol: r for r in rows}


def summarize(db: Session, portfolio: Portfolio) -> PortfolioSummary:
    txns = db.scalars(
        select(Transaction).where(Transaction.portfolio_id == portfolio.id)
    ).all()
    positions = _replay(list(txns))

    open_symbols = [s for s, p in positions.items() if p.quantity > ZERO]
    quotes = prices.get_quotes(open_symbols) if open_symbols else {}
    instruments = _instrument_map(db, open_symbols)

    def last_price(symbol: str) -> tuple[Decimal, bool]:
        """Price for valuation, plus whether it is a real quote.

        With live market data a single delisted or mistyped ticker would
        otherwise 500 the whole summary. Falling back to average cost values
        the position at what was paid -- P&L shows 0 rather than a fabricated
        number -- and `has_quote` lets the UI say so.
        """
        quote = quotes.get(symbol)
        if quote is not None:
            return quote.price, True
        return positions[symbol].avg_cost, False

    total_value = sum(
        (positions[s].quantity * last_price(s)[0] for s in open_symbols), ZERO
    )

    holdings: list[HoldingOut] = []
    for symbol in sorted(open_symbols):
        pos = positions[symbol]
        last, has_quote = last_price(symbol)
        value = pos.quantity * last
        pl = value - pos.cost_basis
        inst = instruments.get(symbol)
        holdings.append(
            HoldingOut(
                symbol=symbol,
                name=inst.name if inst else "",
                asset_class=inst.asset_class if inst else "equity",
                quantity=pos.quantity,
                avg_cost=pos.avg_cost.quantize(Decimal("0.0001")),
                cost_basis=_money(pos.cost_basis),
                last_price=last,
                market_value=_money(value),
                unrealized_pl=_money(pl),
                unrealized_pl_pct=_pct(pl, pos.cost_basis),
                weight_pct=_pct(value, total_value),
                has_quote=has_quote,
            )
        )

    holdings.sort(key=lambda h: h.market_value, reverse=True)
    total_cost = sum((h.cost_basis for h in holdings), ZERO)
    total_pl = total_value - total_cost

    return PortfolioSummary(
        portfolio_id=portfolio.id,
        name=portfolio.name,
        base_currency=portfolio.base_currency,
        market_value=_money(total_value),
        cost_basis=_money(total_cost),
        unrealized_pl=_money(total_pl),
        unrealized_pl_pct=_pct(total_pl, total_cost),
        realized_pl=_money(sum((p.realized_pl for p in positions.values()), ZERO)),
        dividend_income=_money(sum((p.dividends for p in positions.values()), ZERO)),
        holdings=holdings,
    )


def allocation(summary: PortfolioSummary, by: str = "symbol") -> list[AllocationSlice]:
    buckets: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for h in summary.holdings:
        key = h.symbol if by == "symbol" else h.asset_class.value
        buckets[key] += h.market_value

    total = sum(buckets.values(), ZERO)
    slices = [
        AllocationSlice(key=k, market_value=_money(v), weight_pct=_pct(v, total))
        for k, v in buckets.items()
    ]
    slices.sort(key=lambda s: s.market_value, reverse=True)
    return slices


def performance(
    db: Session, portfolio: Portfolio, days: int = 180
) -> list[PerformancePoint]:
    """Value the portfolio on each past day using that day's closing prices.

    Note this is a *point-in-time revaluation*, not a time-weighted return: it
    includes the effect of deposits and withdrawals, which is what you want for
    "what is this worth" and not what you want for "how good is my stock
    picking".
    """
    end = date.today()
    start = end - timedelta(days=days)

    txns = sorted(
        db.scalars(
            select(Transaction).where(Transaction.portfolio_id == portfolio.id)
        ).all(),
        key=lambda t: (t.executed_at, t.id),
    )
    if not txns:
        return []

    symbols = sorted({t.symbol for t in txns})
    # One fetch per symbol for the whole window beats one per symbol per day.
    closes: dict[str, dict[date, Decimal]] = {
        s: {c.date: c.close for c in prices.get_candles(s, start, end)} for s in symbols
    }

    points: list[PerformancePoint] = []
    last_close: dict[str, Decimal] = {}
    idx = 0
    running: list[Transaction] = []

    day = start
    while day <= end:
        while idx < len(txns) and txns[idx].executed_at <= day:
            running.append(txns[idx])
            idx += 1

        if running:
            positions = _replay(running)
            value = ZERO
            cost = ZERO
            for symbol, pos in positions.items():
                if pos.quantity <= ZERO:
                    continue
                price = closes.get(symbol, {}).get(day) or last_close.get(symbol)
                if price is None:
                    continue
                last_close[symbol] = price
                value += pos.quantity * price
                cost += pos.cost_basis
            # Carry forward the latest known close over market holidays.
            for symbol in symbols:
                if (p := closes.get(symbol, {}).get(day)) is not None:
                    last_close[symbol] = p

            points.append(
                PerformancePoint(
                    date=day, market_value=_money(value), cost_basis=_money(cost)
                )
            )
        day += timedelta(days=1)

    return points
