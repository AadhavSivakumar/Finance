"""Market analytics endpoints.

Thin wrappers over services/queries.py -- the same functions the static
exporter calls, so the hosted JSON and the live API cannot diverge.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from ..db import get_db
from ..services import queries

router = APIRouter(prefix="/api", tags=["market"])


@router.get("/overview")
def overview(db: Session = Depends(get_db)) -> dict:
    """Everything the landing tab needs, in one round trip."""
    return {
        "regime": queries.regime(db),
        "freshness": queries.freshness(db),
        "sectors": queries.sector_rotation(db),
        "models": queries.model_runs(db),
    }


@router.get("/movers")
def movers(db: Session = Depends(get_db)) -> list[dict]:
    return queries.movers(db)


@router.get("/sectors")
def sectors(db: Session = Depends(get_db)) -> list[dict]:
    return queries.sector_rotation(db)


@router.get("/regime")
def regime(db: Session = Depends(get_db)) -> dict:
    return queries.regime(db)


@router.get("/signals")
def signals(
    days: int = Query(3, ge=1, le=30),
    limit: int = Query(400, ge=1, le=2000),
    db: Session = Depends(get_db),
) -> list[dict]:
    return queries.signals(db, days=days, limit=limit)


@router.get("/models")
def models(db: Session = Depends(get_db)) -> list[dict]:
    return queries.model_runs(db)


@router.get("/predictions")
def predictions(
    target: str = Query("spike_2atr", pattern="^(spike_2atr|up_5d)$"),
    limit: int = Query(40, ge=1, le=200),
    db: Session = Depends(get_db),
) -> list[dict]:
    return queries.predictions(db, target=target, limit=limit)


@router.get("/correlations")
def correlations(db: Session = Depends(get_db)) -> dict:
    return queries.correlations(db)


@router.get("/macro")
def macro(db: Session = Depends(get_db)) -> list[dict]:
    return queries.macro(db)


@router.get("/history/{symbol}")
def history(
    symbol: str, days: int = Query(400, ge=20, le=2000), db: Session = Depends(get_db)
) -> list[dict]:
    rows = queries.history(db, symbol.upper(), days=days)
    if not rows:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"No history for {symbol}")
    return rows


@router.get("/freshness")
def freshness(db: Session = Depends(get_db)) -> dict:
    return queries.freshness(db)


@router.get("/news")
def news(limit: int = Query(60, ge=1, le=300), db: Session = Depends(get_db)) -> list[dict]:
    return queries.news(db, limit=limit)


@router.get("/metrics")
def metrics() -> list[dict]:
    """Definitions for every metric shown in the UI."""
    return queries.metrics()
