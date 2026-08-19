"""SaaS / business finance metrics: MRR, ARR, burn, runway, margin.

Recognition rules (accrual, stated explicitly because every tool picks
differently):

* ``monthly``  streams recognize their full amount in every active month.
* ``annual``   streams recognize ``amount / 12`` per active month (ratable),
                which is also how they contribute to MRR.
* ``one_time`` streams recognize the full amount in their start month and
                contribute **nothing** to MRR -- that is the whole point of the
                "recurring" in Monthly Recurring Revenue.

Expenses follow the same three rules.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from dateutil.relativedelta import relativedelta
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import CashSnapshot, Expense, Interval, RevenueStream
from ..schemas import BusinessSummary, ExpenseBreakdown, MonthlyPoint

ZERO = Decimal("0")
TWELVE = Decimal("12")

# Expense categories treated as cost of revenue for the gross-margin figure.
# Everything else (salaries for R&D, marketing, G&A) sits below the line.
COGS_CATEGORIES = {"cogs", "hosting", "infrastructure", "cloud", "payment processing", "support"}


def _money(v: Decimal) -> Decimal:
    return v.quantize(Decimal("0.01"))


def _pct(part: Decimal, whole: Decimal) -> Decimal:
    if whole == ZERO:
        return ZERO
    return (part / whole * 100).quantize(Decimal("0.01"))


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _active(item, month: date) -> bool:
    """Is the stream/expense live at any point during ``month``?"""
    month_end = month + relativedelta(months=1, days=-1)
    if item.start_date > month_end:
        return False
    if item.end_date is not None and item.end_date < month:
        return False
    return True


def _recurring_monthly_amount(item) -> Decimal:
    if item.interval is Interval.monthly:
        return item.amount
    if item.interval is Interval.annual:
        return item.amount / TWELVE
    return ZERO  # one_time is not recurring


def _recognized_in_month(item, month: date) -> Decimal:
    if item.interval is Interval.one_time:
        return item.amount if _month_start(item.start_date) == month else ZERO
    if not _active(item, month):
        return ZERO
    return _recurring_monthly_amount(item)


def mrr(streams: list[RevenueStream], month: date) -> Decimal:
    return sum(
        (_recurring_monthly_amount(s) for s in streams if _active(s, month)), ZERO
    )


def monthly_expense_total(expenses: list[Expense], month: date) -> Decimal:
    return sum((_recognized_in_month(e, month) for e in expenses), ZERO)


def summarize(db: Session, months: int = 12, as_of: date | None = None) -> BusinessSummary:
    as_of = as_of or date.today()
    current = _month_start(as_of)

    streams = list(db.scalars(select(RevenueStream)))
    expenses = list(db.scalars(select(Expense)))
    latest_cash = db.scalars(
        select(CashSnapshot).order_by(CashSnapshot.as_of.desc()).limit(1)
    ).first()

    series: list[MonthlyPoint] = []
    for i in range(months - 1, -1, -1):
        month = current - relativedelta(months=i)
        revenue = sum((_recognized_in_month(s, month) for s in streams), ZERO)
        exp = monthly_expense_total(expenses, month)
        series.append(
            MonthlyPoint(
                month=month.strftime("%Y-%m"),
                revenue=_money(revenue),
                mrr=_money(mrr(streams, month)),
                expenses=_money(exp),
                net=_money(revenue - exp),
            )
        )

    current_mrr = mrr(streams, current)
    current_expenses = monthly_expense_total(expenses, current)
    current_revenue = sum((_recognized_in_month(s, current) for s in streams), ZERO)

    cogs = sum(
        (
            _recognized_in_month(e, current)
            for e in expenses
            if e.category.strip().lower() in COGS_CATEGORIES
        ),
        ZERO,
    )

    net_burn = current_expenses - current_revenue
    cash = latest_cash.amount if latest_cash else ZERO
    runway = (
        (cash / net_burn).quantize(Decimal("0.1"))
        if net_burn > ZERO and cash > ZERO
        else None
    )

    growth = ZERO
    if len(series) >= 2 and series[-2].revenue != ZERO:
        growth = _pct(series[-1].revenue - series[-2].revenue, series[-2].revenue)

    return BusinessSummary(
        as_of=as_of,
        mrr=_money(current_mrr),
        arr=_money(current_mrr * TWELVE),
        monthly_expenses=_money(current_expenses),
        net_burn=_money(net_burn),
        gross_margin_pct=_pct(current_revenue - cogs, current_revenue),
        cash=_money(cash),
        runway_months=runway,
        mom_revenue_growth_pct=growth,
        series=series,
    )


def expense_breakdown(db: Session, as_of: date | None = None) -> list[ExpenseBreakdown]:
    month = _month_start(as_of or date.today())
    expenses = list(db.scalars(select(Expense)))

    buckets: dict[str, Decimal] = defaultdict(lambda: ZERO)
    for e in expenses:
        amount = _recognized_in_month(e, month)
        if amount:
            buckets[e.category] += amount

    total = sum(buckets.values(), ZERO)
    rows = [
        ExpenseBreakdown(
            category=k, monthly_amount=_money(v), share_pct=_pct(v, total)
        )
        for k, v in buckets.items()
    ]
    rows.sort(key=lambda r: r.monthly_amount, reverse=True)
    return rows
