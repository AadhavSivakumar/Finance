from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Portfolio, Transaction
from ..schemas import (
    AllocationSlice,
    PerformancePoint,
    PortfolioCreate,
    PortfolioOut,
    PortfolioSummary,
    TransactionCreate,
    TransactionOut,
)
from ..services import portfolio_calc

router = APIRouter(prefix="/api/portfolios", tags=["portfolios"])


def _get_portfolio(db: Session, portfolio_id: int) -> Portfolio:
    portfolio = db.get(Portfolio, portfolio_id)
    if portfolio is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Portfolio not found")
    return portfolio


@router.get("", response_model=list[PortfolioOut])
def list_portfolios(db: Session = Depends(get_db)):
    return db.scalars(select(Portfolio).order_by(Portfolio.name)).all()


@router.post("", response_model=PortfolioOut, status_code=status.HTTP_201_CREATED)
def create_portfolio(payload: PortfolioCreate, db: Session = Depends(get_db)):
    portfolio = Portfolio(**payload.model_dump())
    db.add(portfolio)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Portfolio name already exists")
    db.refresh(portfolio)
    return portfolio


@router.delete("/{portfolio_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_portfolio(portfolio_id: int, db: Session = Depends(get_db)):
    db.delete(_get_portfolio(db, portfolio_id))
    db.commit()


@router.get("/{portfolio_id}/summary", response_model=PortfolioSummary)
def portfolio_summary(portfolio_id: int, db: Session = Depends(get_db)):
    return portfolio_calc.summarize(db, _get_portfolio(db, portfolio_id))


@router.get("/{portfolio_id}/allocation", response_model=list[AllocationSlice])
def portfolio_allocation(
    portfolio_id: int,
    by: str = Query("symbol", pattern="^(symbol|asset_class)$"),
    db: Session = Depends(get_db),
):
    summary = portfolio_calc.summarize(db, _get_portfolio(db, portfolio_id))
    return portfolio_calc.allocation(summary, by=by)


@router.get("/{portfolio_id}/performance", response_model=list[PerformancePoint])
def portfolio_performance(
    portfolio_id: int,
    days: int = Query(180, ge=7, le=1825),
    db: Session = Depends(get_db),
):
    return portfolio_calc.performance(db, _get_portfolio(db, portfolio_id), days=days)


@router.get("/{portfolio_id}/transactions", response_model=list[TransactionOut])
def list_transactions(
    portfolio_id: int,
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
):
    _get_portfolio(db, portfolio_id)
    return db.scalars(
        select(Transaction)
        .where(Transaction.portfolio_id == portfolio_id)
        .order_by(Transaction.executed_at.desc(), Transaction.id.desc())
        .limit(limit)
    ).all()


@router.post(
    "/{portfolio_id}/transactions",
    response_model=TransactionOut,
    status_code=status.HTTP_201_CREATED,
)
def create_transaction(
    portfolio_id: int, payload: TransactionCreate, db: Session = Depends(get_db)
):
    _get_portfolio(db, portfolio_id)
    txn = Transaction(portfolio_id=portfolio_id, **payload.model_dump())
    db.add(txn)
    db.commit()
    db.refresh(txn)
    return txn


@router.delete(
    "/{portfolio_id}/transactions/{txn_id}", status_code=status.HTTP_204_NO_CONTENT
)
def delete_transaction(portfolio_id: int, txn_id: int, db: Session = Depends(get_db)):
    txn = db.get(Transaction, txn_id)
    if txn is None or txn.portfolio_id != portfolio_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transaction not found")
    db.delete(txn)
    db.commit()
