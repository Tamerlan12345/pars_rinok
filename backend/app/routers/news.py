"""News router — Yahoo Finance RSS ingestion and retrieval."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.news import NewsItem
from app.schemas.news import NewsItemRead
from app.services.data_fetcher import fetch_general_market_news, fetch_yahoo_news

router = APIRouter(prefix="/news", tags=["news"])


async def _upsert_news_items(db: AsyncSession, items: list[dict]) -> list[NewsItem]:
    """Insert news items, silently skip duplicates (unique URL constraint)."""
    saved: list[NewsItem] = []
    for item in items:
        existing = await db.execute(select(NewsItem).where(NewsItem.url == item["url"]))
        if existing.scalar_one_or_none():
            continue
        news = NewsItem(
            ticker_symbol=item.get("ticker_symbol"),
            title=item["title"],
            url=item["url"],
            published_at=item.get("published_at"),
            source=item.get("source"),
            summary=item.get("summary"),
        )
        db.add(news)
        saved.append(news)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        return []
    return saved


@router.get("/fetch", response_model=list[NewsItemRead])
async def fetch_news(
    ticker: str = Query(..., min_length=1, max_length=20),
    db: AsyncSession = Depends(get_db),
) -> list[NewsItemRead]:
    ticker = ticker.upper().strip()
    raw_items = await fetch_yahoo_news(ticker, max_items=20)
    await _upsert_news_items(db, raw_items)

    # Return from DB (includes previously fetched)
    result = await db.execute(
        select(NewsItem)
        .where(NewsItem.ticker_symbol == ticker)
        .order_by(desc(NewsItem.published_at))
        .limit(30)
    )
    return [NewsItemRead.model_validate(n) for n in result.scalars().all()]


@router.get("/latest", response_model=list[NewsItemRead])
async def get_latest_news(
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
) -> list[NewsItemRead]:
    result = await db.execute(
        select(NewsItem)
        .order_by(desc(NewsItem.published_at))
        .limit(limit)
    )
    return [NewsItemRead.model_validate(n) for n in result.scalars().all()]


@router.get("/general", response_model=list[NewsItemRead])
async def fetch_general_news(db: AsyncSession = Depends(get_db)) -> list[NewsItemRead]:
    """Fetch and store general market news from Yahoo Finance RSS index."""
    raw_items = await fetch_general_market_news(max_items=30)
    await _upsert_news_items(db, raw_items)

    result = await db.execute(
        select(NewsItem)
        .where(NewsItem.ticker_symbol.is_(None))
        .order_by(desc(NewsItem.published_at))
        .limit(50)
    )
    return [NewsItemRead.model_validate(n) for n in result.scalars().all()]


@router.get("/ticker/{symbol}", response_model=list[NewsItemRead])
async def get_news_by_ticker(
    symbol: str,
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_db),
) -> list[NewsItemRead]:
    symbol = symbol.upper().strip()
    result = await db.execute(
        select(NewsItem)
        .where(NewsItem.ticker_symbol == symbol)
        .order_by(desc(NewsItem.published_at))
        .limit(limit)
    )
    return [NewsItemRead.model_validate(n) for n in result.scalars().all()]
