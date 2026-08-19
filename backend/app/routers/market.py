from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import WatchlistItem
from ..schemas import Candle, Quote, WatchlistCreate, WatchlistOut
from ..services import prices

router = APIRouter(prefix="/api/market", tags=["market"])


@router.get("/quotes", response_model=list[Quote])
def quotes(symbols: str = Query(..., description="Comma-separated, e.g. AAPL,MSFT")):
    wanted = [s.strip().upper() for s in symbols.split(",") if s.strip()]
    if not wanted:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No symbols provided")
    if len(wanted) > 50:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Too many symbols (max 50)")

    found = prices.get_quotes(wanted)
    # Partial success is fine (one bad ticker among many), but if nothing came
    # back the upstream is down and that deserves a 502 rather than an empty
    # list the UI would render as "no data".
    if not found:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY, "Market data unavailable for all requested symbols"
        )
    return list(found.values())


@router.get("/candles/{symbol}", response_model=list[Candle])
def candles(symbol: str, days: int = Query(180, ge=5, le=1825)):
    end = date.today()
    try:
        return prices.get_candles(symbol, end - timedelta(days=days), end)
    except prices.MarketDataError as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc))


@router.get("/watchlist", response_model=list[WatchlistOut])
def list_watchlist(db: Session = Depends(get_db)):
    return db.scalars(select(WatchlistItem).order_by(WatchlistItem.symbol)).all()


@router.post(
    "/watchlist", response_model=WatchlistOut, status_code=status.HTTP_201_CREATED
)
def add_watchlist(payload: WatchlistCreate, db: Session = Depends(get_db)):
    item = WatchlistItem(**payload.model_dump())
    db.add(item)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Symbol already on watchlist")
    db.refresh(item)
    return item


@router.delete("/watchlist/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_watchlist(item_id: int, db: Session = Depends(get_db)):
    item = db.get(WatchlistItem, item_id)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Watchlist item not found")
    db.delete(item)
    db.commit()
