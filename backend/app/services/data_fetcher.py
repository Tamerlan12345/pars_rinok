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


def _make_yahoo_session() -> "requests.Session":
    """
    Build a requests.Session with full browser headers and a primed Yahoo Finance
    cookie jar. Without the crumb cookie that Yahoo sets on first page load,
    the v8/v10 data API returns empty JSON on cloud provider IPs.
    """
    import requests

    session = requests.Session()
    session.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Accept": (
            "text/html,application/xhtml+xml,application/xml;q=0.9,"
            "image/avif,image/webp,image/apng,*/*;q=0.8"
        ),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept-Encoding": "gzip, deflate, br",
        "Connection": "keep-alive",
        "Upgrade-Insecure-Requests": "1",
    })
    # Prime cookie jar — Yahoo issues a consent/crumb cookie on first GET.
    try:
        session.get("https://finance.yahoo.com", timeout=8)
    except Exception as exc:
        logger.debug("Yahoo cookie prime failed (non-fatal): %s", exc)
    return session


def _fetch_ohlcv_sync(ticker: str, period: str, interval: str) -> list[dict]:
    """
    Blocking yfinance download — runs inside asyncio.to_thread().
    Uses Ticker.history() (more reliable with a custom session than yf.download).
    Returns a list of candle dicts; empty list on any error.
    """
    import yfinance as yf  # imported inside thread to avoid import-time side effects

    session = _make_yahoo_session()
    try:
        t = yf.Ticker(ticker, session=session)
        df = t.history(period=period, interval=interval, auto_adjust=True)
    except Exception as exc:
        logger.warning("yfinance fetch failed for %s (%s/%s): %s", ticker, period, interval, exc)
        return []

    if df is None or df.empty:
        logger.warning("yfinance returned empty DataFrame for %s (%s/%s)", ticker, period, interval)
        return []

    candles: list[dict] = []
    for ts, row in df.iterrows():
        try:
            open_ = float(row["Open"])
            high = float(row["High"])
            low = float(row["Low"])
            close = float(row["Close"])
            volume = float(row.get("Volume", 0) or 0)
        except (KeyError, TypeError, ValueError):
            continue

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
    Blocking RSS fetch — runs inside asyncio.to_thread().
    Uses urllib with a browser User-Agent because Yahoo Finance blocks
    default Python UA and most cloud provider IP ranges with plain feedparser.
    Returns list of news dicts; empty list on error.
    """
    import urllib.request

    _BROWSER_UA = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )

    try:
        req = urllib.request.Request(url, headers={"User-Agent": _BROWSER_UA})
        with urllib.request.urlopen(req, timeout=10) as resp:
            raw_bytes = resp.read()
        feed = feedparser.parse(raw_bytes)
    except Exception as exc:
        logger.warning("RSS fetch failed for %s: %s", url, exc)
        return []

    if not feed.entries:
        logger.warning("RSS feed returned 0 entries for %s (bozo=%s)", url, getattr(feed, "bozo", None))
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
