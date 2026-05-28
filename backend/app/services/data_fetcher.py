"""
Data fetcher service — OHLCV candles via yfinance, news via Yahoo Finance RSS.

All blocking I/O (yfinance, feedparser) is wrapped in asyncio.to_thread() so
the event loop is not blocked during network calls or DataFrame construction.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import feedparser  # type: ignore[import-untyped]

logger = logging.getLogger("centras.data_fetcher")

# Accepted period and interval values per yfinance documentation.
_VALID_PERIODS = {
    "1d", "5d", "1mo", "3mo", "6mo", "1y", "2y", "5y", "10y", "ytd", "max",
}
_VALID_INTERVALS = {
    "1m", "2m", "5m", "15m", "30m", "60m", "90m", "1h", "1d", "5d", "1wk", "1mo", "3mo",
}


def _fetch_ohlcv_sync(ticker: str, period: str, interval: str) -> list[dict]:
    """
    Blocking yfinance download — runs inside asyncio.to_thread().
    Returns a list of candle dicts; empty list on any error.
    """
    import yfinance as yf  # imported inside thread to avoid import-time side effects

    try:
        import requests
        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        })
        df = yf.download(
            tickers=ticker,
            period=period,
            interval=interval,
            auto_adjust=True,
            progress=False,
            threads=False,
            session=session,
        )
    except Exception as exc:
        logger.warning("yfinance download failed for %s (%s/%s): %s", ticker, period, interval, exc)
        return []

    if df is None or df.empty:
        logger.warning("yfinance returned empty DataFrame for %s (%s/%s)", ticker, period, interval)
        return []

    candles: list[dict] = []
    for ts, row in df.iterrows():
        # yfinance may return MultiIndex columns when downloading a single ticker.
        def _get(col: str) -> float:
            try:
                val = row[col]
                # MultiIndex case: row[(col, ticker)]
                if hasattr(val, "__len__") and not isinstance(val, (int, float)):
                    val = row[(col, ticker)]
                return float(val)
            except (KeyError, TypeError, ValueError):
                return 0.0

        open_ = _get("Open")
        high = _get("High")
        low = _get("Low")
        close = _get("Close")
        volume = _get("Volume")

        if close <= 0:
            # Skip corrupt/delisted rows.
            continue

        # Normalize timestamp to UTC-aware datetime.
        if hasattr(ts, "tzinfo") and ts.tzinfo is not None:
            timestamp = ts.to_pydatetime()
        else:
            timestamp = ts.to_pydatetime().replace(tzinfo=timezone.utc)

        candles.append({
            "timestamp": timestamp,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        })

    return candles


async def fetch_ohlcv(
    ticker: str,
    period: str = "1mo",
    interval: str = "1d",
) -> list[dict]:
    """
    Fetch OHLCV candles via yfinance, running in a thread pool.

    Args:
        ticker:   Stock symbol, e.g. "AAPL".
        period:   yfinance period string, e.g. "1mo".
        interval: yfinance interval string, e.g. "1d".

    Returns:
        List of candle dicts: {timestamp, open, high, low, close, volume}.
        Returns empty list if yfinance fails — callers must handle this case.
    """
    if period not in _VALID_PERIODS:
        logger.warning("Unrecognised period '%s' — passing to yfinance anyway", period)
    if interval not in _VALID_INTERVALS:
        logger.warning("Unrecognised interval '%s' — passing to yfinance anyway", interval)

    return await asyncio.to_thread(_fetch_ohlcv_sync, ticker.upper(), period, interval)


def _fetch_rss_sync(url: str, max_items: int) -> list[dict]:
    """
    Blocking feedparser call — runs inside asyncio.to_thread().
    Returns list of news dicts; empty list on error.
    """
    try:
        feed = feedparser.parse(url)
    except Exception as exc:
        logger.warning("feedparser failed for %s: %s", url, exc)
        return []

    items: list[dict] = []
    for entry in feed.entries[:max_items]:
        title: str = getattr(entry, "title", "") or ""
        link: str = getattr(entry, "link", "") or ""

        if not title or not link:
            continue

        # Parse publication date — feedparser uses time.struct_time in published_parsed.
        published_at: Optional[datetime] = None
        if hasattr(entry, "published_parsed") and entry.published_parsed:
            try:
                import calendar
                ts = calendar.timegm(entry.published_parsed)
                published_at = datetime.fromtimestamp(ts, tz=timezone.utc)
            except Exception:
                published_at = None

        summary: str = ""
        if hasattr(entry, "summary"):
            summary = entry.summary or ""
        elif hasattr(entry, "description"):
            summary = entry.description or ""

        source: str = getattr(feed.feed, "title", "") or ""

        items.append({
            "title": title[:512],
            "url": link[:2048],
            "published_at": published_at,
            "source": source[:255] if source else None,
            "summary": summary or None,
        })

    return items


async def fetch_yahoo_news(ticker: str, max_items: int = 20) -> list[dict]:
    """
    Fetch ticker-specific news from Yahoo Finance RSS feed.

    Args:
        ticker:    Stock symbol, e.g. "AAPL".
        max_items: Maximum number of items to return.

    Returns:
        List of news dicts: {title, url, published_at, source, summary}.
        Returns empty list if feed is unavailable.
    """
    url = f"https://finance.yahoo.com/rss/headline?s={ticker.upper()}"
    return await asyncio.to_thread(_fetch_rss_sync, url, max_items)


async def fetch_general_market_news(max_items: int = 30) -> list[dict]:
    """
    Fetch general market news from Yahoo Finance index RSS feed.

    Returns:
        List of news dicts: {title, url, published_at, source, summary}.
        Returns empty list if feed is unavailable.
    """
    url = "https://finance.yahoo.com/news/rssindex"
    return await asyncio.to_thread(_fetch_rss_sync, url, max_items)
