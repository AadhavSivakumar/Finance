from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import CashSnapshot, Expense, RevenueStream
from ..schemas import (
    BusinessSummary,
    CashSnapshotCreate,
    CashSnapshotOut,
    ExpenseBreakdown,
    ExpenseCreate,
    ExpenseOut,
    RevenueStreamCreate,
    RevenueStreamOut,
)
from ..services import business_metrics

router = APIRouter(prefix="/api/business", tags=["business"])


@router.get("/summary", response_model=BusinessSummary)
def summary(
    months: int = Query(12, ge=1, le=60),
    as_of: date | None = None,
    db: Session = Depends(get_db),
):
    return business_metrics.summarize(db, months=months, as_of=as_of)


@router.get("/expenses/breakdown", response_model=list[ExpenseBreakdown])
def breakdown(as_of: date | None = None, db: Session = Depends(get_db)):
    return business_metrics.expense_breakdown(db, as_of=as_of)


# --- revenue streams ------------------------------------------------------


@router.get("/revenue", response_model=list[RevenueStreamOut])
def list_revenue(db: Session = Depends(get_db)):
    return db.scalars(
        select(RevenueStream).order_by(RevenueStream.start_date.desc())
    ).all()


@router.post(
    "/revenue", response_model=RevenueStreamOut, status_code=status.HTTP_201_CREATED
)
def create_revenue(payload: RevenueStreamCreate, db: Session = Depends(get_db)):
    _validate_dates(payload.start_date, payload.end_date)
    row = RevenueStream(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/revenue/{row_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_revenue(row_id: int, db: Session = Depends(get_db)):
    _delete(db, RevenueStream, row_id, "Revenue stream")


# --- expenses -------------------------------------------------------------


@router.get("/expenses", response_model=list[ExpenseOut])
def list_expenses(db: Session = Depends(get_db)):
    return db.scalars(select(Expense).order_by(Expense.start_date.desc())).all()


@router.post("/expenses", response_model=ExpenseOut, status_code=status.HTTP_201_CREATED)
def create_expense(payload: ExpenseCreate, db: Session = Depends(get_db)):
    _validate_dates(payload.start_date, payload.end_date)
    row = Expense(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/expenses/{row_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_expense(row_id: int, db: Session = Depends(get_db)):
    _delete(db, Expense, row_id, "Expense")


# --- cash -----------------------------------------------------------------


@router.get("/cash", response_model=list[CashSnapshotOut])
def list_cash(db: Session = Depends(get_db)):
    return db.scalars(select(CashSnapshot).order_by(CashSnapshot.as_of.desc())).all()


@router.post("/cash", response_model=CashSnapshotOut, status_code=status.HTTP_201_CREATED)
def create_cash(payload: CashSnapshotCreate, db: Session = Depends(get_db)):
    existing = db.scalar(
        select(CashSnapshot).where(CashSnapshot.as_of == payload.as_of)
    )
    if existing:  # upsert: one balance per date
        existing.amount = payload.amount
        existing.currency = payload.currency
        db.commit()
        db.refresh(existing)
        return existing

    row = CashSnapshot(**payload.model_dump())
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


# --- helpers --------------------------------------------------------------


def _validate_dates(start: date, end: date | None) -> None:
    if end is not None and end < start:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "end_date must be on or after start_date"
        )


def _delete(db: Session, model, row_id: int, label: str) -> None:
    row = db.get(model, row_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"{label} not found")
    db.delete(row)
    db.commit()
