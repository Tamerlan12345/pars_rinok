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


def _period_to_days(period: str) -> int:
    """Convert yfinance period string to approximate number of calendar days."""
    _map = {
        "1d": 1, "5d": 5, "1mo": 31, "3mo": 92,
        "6mo": 183, "1y": 365, "2y": 730, "5y": 1826, "10y": 3653,
        "ytd": 365, "max": 3653,
    }
    return _map.get(period, 92)


def _df_to_candles(df: "pandas.DataFrame") -> list[dict]:
    """Convert a OHLCV DataFrame (any source) to candle dicts."""
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
            continue
        # Ensure timestamp is naive (UTC) to avoid asyncpg naive/aware subtraction error
        timestamp = ts.to_pydatetime()
        if timestamp.tzinfo is not None:
            timestamp = timestamp.replace(tzinfo=None)
        candles.append({
            "timestamp": timestamp,
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        })
    return candles


def _fetch_via_yahoo_chart(ticker: str, period: str, interval: str) -> list[dict]:
    """
    Fallback source: Yahoo Finance Chart API via query2.finance.yahoo.com.
    This endpoint differs from what yfinance uses and is often reachable from
    cloud IPs where the yfinance data download is blocked.
    Uses stdlib http.cookiejar — no extra dependencies.
    """
    import http.cookiejar
    import json
    import urllib.request
    from datetime import timezone as tz

    _UA = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    _HEADERS = {
        "User-Agent": _UA,
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Connection": "keep-alive",
    }

    # Build an opener with a shared cookie jar so the consent cookie
    # obtained from the homepage carries into the chart API request.
    jar = http.cookiejar.CookieJar()
    opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))

    try:
        prime_req = urllib.request.Request(
            f"https://finance.yahoo.com/quote/{ticker}/",
            headers=_HEADERS,
        )
        opener.open(prime_req, timeout=8)
    except Exception as exc:
        logger.debug("Yahoo chart cookie prime failed (non-fatal): %s", exc)

    url = (
        f"https://query2.finance.yahoo.com/v8/finance/chart/{ticker}"
        f"?range={period}&interval={interval}&includePrePost=false&events=div%2Csplits"
    )
    chart_req = urllib.request.Request(
        url,
        headers={**_HEADERS, "Referer": f"https://finance.yahoo.com/quote/{ticker}/"},
    )

    try:
        resp = opener.open(chart_req, timeout=12)
        data = json.loads(resp.read())
    except Exception as exc:
        logger.warning("Yahoo chart API request failed for %s: %s", ticker, exc)
        return []

    try:
        result = data["chart"]["result"][0]
        timestamps = result["timestamp"]
        quote = result["indicators"]["quote"][0]
        opens = quote.get("open") or []
        highs = quote.get("high") or []
        lows = quote.get("low") or []
        closes = quote.get("close") or []
        volumes = quote.get("volume") or []
        # Use adjusted close when available.
        try:
            adj_closes = result["indicators"]["adjclose"][0].get("adjclose") or closes
        except Exception:
            adj_closes = closes
    except (KeyError, IndexError, TypeError) as exc:
        logger.warning("Yahoo chart API parse error for %s: %s", ticker, exc)
        return []

    candles: list[dict] = []
    for i, ts in enumerate(timestamps):
        try:
            close = float((adj_closes[i] if i < len(adj_closes) else None) or closes[i] or 0)
            open_ = float(opens[i] or 0) if i < len(opens) else 0.0
            high = float(highs[i] or 0) if i < len(highs) else 0.0
            low = float(lows[i] or 0) if i < len(lows) else 0.0
            volume = float(volumes[i] or 0) if i < len(volumes) else 0.0
        except (TypeError, ValueError):
            continue
        if close <= 0:
            continue
        candles.append({
            "timestamp": datetime.fromtimestamp(ts, tz=tz.utc).replace(tzinfo=None),
            "open": open_,
            "high": high,
            "low": low,
            "close": close,
            "volume": volume,
        })

    if not candles:
        logger.warning("Yahoo chart API returned 0 candles for %s", ticker)
    return candles


def _fetch_ohlcv_sync(ticker: str, period: str, interval: str) -> list[dict]:
    """
    Blocking OHLCV fetch — runs inside asyncio.to_thread().

    Strategy:
      1. Try yfinance with a browser-impersonating session + primed cookie jar.
      2. If yfinance returns empty (Yahoo blocks cloud ASNs), fall back to 
         direct Yahoo Chart API.
    """
    import yfinance as yf

    session = _make_yahoo_session()
    df = None
    try:
        t = yf.Ticker(ticker, session=session)
        df = t.history(period=period, interval=interval, auto_adjust=True)
    except Exception as exc:
        logger.warning("yfinance fetch failed for %s: %s", ticker, exc)

    if df is not None and not df.empty:
        return _df_to_candles(df)

    # yfinance returned nothing — Yahoo is blocking this IP.
    logger.warning(
        "yfinance empty for %s (%s/%s) — falling back to Yahoo Chart API",
        ticker, period, interval,
    )
    return _fetch_via_yahoo_chart(ticker, period, interval)


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
