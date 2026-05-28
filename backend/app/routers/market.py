"""Market data router — OHLCV fetch and candle queries."""
from __future__ import annotations

from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.candle import Candle
from app.models.ticker import Ticker
from app.routers.auth import get_current_user
from app.schemas.market import (
    CandleRead,
    MarketFetchResponse,
    TickerCreate,
    TickerRead,
)
from app.services.data_fetcher import fetch_ohlcv

router = APIRouter(prefix="/market", tags=["market"])

# Simple in-memory cache: ticker+period+interval → (fetched_at, count)
_fetch_cache: dict[str, datetime] = {}
_CACHE_TTL_SECONDS = 3600  # 1 hour


def _cache_key(ticker: str, period: str, interval: str) -> str:
    return f"{ticker}:{period}:{interval}"


@router.get("/fetch", response_model=MarketFetchResponse)
async def fetch_market_data(
    ticker: str = Query(..., min_length=1, max_length=20),
    period: str = Query("1mo"),
    interval: str = Query("1d"),
    db: AsyncSession = Depends(get_db),
) -> MarketFetchResponse:
    ticker = ticker.upper().strip()
    cache_key = _cache_key(ticker, period, interval)
    now = datetime.utcnow()
    from_cache = False

    # Check cache freshness
    last_fetched = _fetch_cache.get(cache_key)
    if last_fetched and (now - last_fetched).total_seconds() < _CACHE_TTL_SECONDS:
        from_cache = True
    else:
        # Fetch from yfinance and upsert
        raw_candles = await fetch_ohlcv(ticker, period, interval)

        if raw_candles:
            # Ensure ticker exists in DB
            result = await db.execute(select(Ticker).where(Ticker.symbol == ticker))
            tkr = result.scalar_one_or_none()
            if not tkr:
                tkr = Ticker(symbol=ticker)
                db.add(tkr)
                await db.flush()

            # Upsert candles (INSERT ... ON CONFLICT DO NOTHING via filter)
            existing_result = await db.execute(
                select(Candle.timestamp).where(
                    Candle.ticker_symbol == ticker,
                    Candle.interval == interval,
                )
            )
            existing_timestamps = set(existing_result.scalars().all())

            new_candles = [
                Candle(
                    ticker_id=tkr.id,
                    ticker_symbol=ticker,
                    timestamp=c["timestamp"],
                    open=c["open"],
                    high=c["high"],
                    low=c["low"],
                    close=c["close"],
                    volume=c["volume"],
                    interval=interval,
                )
                for c in raw_candles
                if c["timestamp"] not in existing_timestamps
            ]
            if new_candles:
                db.add_all(new_candles)
                await db.flush()

            _fetch_cache[cache_key] = now

    # Query DB for candles
    stmt = (
        select(Candle)
        .where(Candle.ticker_symbol == ticker, Candle.interval == interval)
        .order_by(Candle.timestamp)
        .limit(500)
    )
    result = await db.execute(stmt)
    candles = result.scalars().all()

    return MarketFetchResponse(
        ticker=ticker,
        candles=[CandleRead.model_validate(c) for c in candles],
        count=len(candles),
        from_cache=from_cache,
    )


@router.get("/tickers", response_model=list[TickerRead])
async def list_tickers(db: AsyncSession = Depends(get_db)) -> list[TickerRead]:
    result = await db.execute(
        select(Ticker).where(Ticker.is_active.is_(True)).order_by(Ticker.symbol)
    )
    tickers = result.scalars().all()
    return [TickerRead.model_validate(t) for t in tickers]


@router.post("/tickers", response_model=TickerRead, status_code=status.HTTP_201_CREATED)
async def add_ticker(
    body: TickerCreate,
    db: AsyncSession = Depends(get_db),
    _: str = Depends(get_current_user),
) -> TickerRead:
    existing = await db.execute(select(Ticker).where(Ticker.symbol == body.symbol))
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Ticker {body.symbol} already exists",
        )
    ticker = Ticker(symbol=body.symbol, name=body.name, sector=body.sector)
    db.add(ticker)
    await db.flush()
    return TickerRead.model_validate(ticker)


@router.get("/candles", response_model=list[CandleRead])
async def get_candles(
    ticker: str = Query(...),
    interval: str = Query("1d"),
    limit: int = Query(200, ge=1, le=500),
    db: AsyncSession = Depends(get_db),
) -> list[CandleRead]:
    ticker = ticker.upper().strip()
    result = await db.execute(
        select(Candle)
        .where(Candle.ticker_symbol == ticker, Candle.interval == interval)
        .order_by(desc(Candle.timestamp))
        .limit(limit)
    )
    candles = result.scalars().all()
    # Return in ascending order for chart rendering
    return [CandleRead.model_validate(c) for c in reversed(candles)]
