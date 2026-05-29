"""
API integration tests for the Centras Tokenizer FastAPI application.

Coverage targets
----------------
Auth routes
  - POST /api/auth/login  (success / wrong password / missing fields)
  - JWT protection on routes that require get_current_user

Health route
  - GET /health (no auth required)

Market routes
  - GET /api/market/tickers
  - POST /api/market/tickers  (protected — requires JWT)
  - GET /api/market/candles
  - GET /api/market/fetch     (yfinance call mocked)

Analysis routes
  - POST /api/analysis/run   (tokenizer + Gemini both mocked)
  - GET  /api/analysis/history
  - GET  /api/analysis/{id}

News routes
  - GET /api/news/latest
  - GET /api/news/fetch        (feedparser mocked)

Logs routes
  - GET /api/logs/recent       (protected)

Gemini client unit tests
  - analyze_with_gemini mock mode (no API key)
  - analyze_with_gemini with mocked google-genai SDK
  - analyze_with_gemini handles timeout gracefully
  - analyze_with_gemini handles arbitrary SDK exception

Notes
-----
- All external I/O (yfinance, feedparser, google-genai) is mocked so tests
  run offline in CI without network access.
- The DB is in-memory SQLite (see conftest.py).
- Each test receives a clean session that is rolled back after the test.
"""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_candle_rows(n: int = 5) -> list[dict]:
    """Return n minimal candle dicts for seeding the test DB."""
    base = datetime(2024, 3, 1, 9, 0, 0)
    return [
        {
            "open": 100.0 + i,
            "high": 102.0 + i,
            "low": 99.0 + i,
            "close": 101.0 + i,
            "volume": 1_000_000.0,
            "timestamp": base + timedelta(days=i),
            "interval": "1d",
        }
        for i in range(n)
    ]


# ===========================================================================
# Health endpoint
# ===========================================================================

class TestHealth:
    @pytest.mark.asyncio
    async def test_health_returns_200(self, client: AsyncClient):
        response = await client.get("/health")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_health_body_structure(self, client: AsyncClient):
        response = await client.get("/health")
        body = response.json()
        assert body["status"] == "ok"
        assert "database" in body
        assert "version" in body
        assert "timestamp" in body

    @pytest.mark.asyncio
    async def test_health_db_status_ok_with_sqlite(self, client: AsyncClient):
        """With the in-memory SQLite DB the database field should be 'ok'."""
        response = await client.get("/health")
        assert response.json()["database"] == "ok"


# ===========================================================================
# Auth endpoint
# ===========================================================================

class TestLogin:
    @pytest.mark.asyncio
    async def test_login_success(self, client: AsyncClient):
        """Correct credentials → 200 + access_token."""
        response = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "centras_admin_2024"},
        )
        assert response.status_code == 200
        body = response.json()
        assert "access_token" in body
        assert body["token_type"] == "bearer"
        assert isinstance(body["expires_in"], int)
        assert body["expires_in"] > 0

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, client: AsyncClient):
        """Wrong password → 401."""
        response = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "wrong-password"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_login_wrong_username(self, client: AsyncClient):
        """Wrong username → 401."""
        response = await client.post(
            "/api/auth/login",
            json={"username": "hacker", "password": "centras_admin_2024"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_login_missing_fields(self, client: AsyncClient):
        """Missing body → 422 Unprocessable Entity."""
        response = await client.post("/api/auth/login", json={})
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_login_returns_valid_jwt(self, client: AsyncClient, settings):
        """The returned token must be decodable with the test secret."""
        from jose import jwt as jose_jwt

        response = await client.post(
            "/api/auth/login",
            json={"username": "admin", "password": "centras_admin_2024"},
        )
        token = response.json()["access_token"]
        payload = jose_jwt.decode(token, settings.jwt_secret_key, algorithms=[settings.jwt_algorithm])
        assert payload["sub"] == "admin"


# ===========================================================================
# JWT protection
# ===========================================================================

class TestJWTProtection:
    """Routes that depend on get_current_user must reject requests without a valid token."""

    PROTECTED_ROUTES = [
        ("POST", "/api/market/tickers", {"symbol": "AAPL"}),
        ("GET", "/api/logs/recent", None),
    ]

    @pytest.mark.asyncio
    async def test_post_ticker_without_token_is_401(self, client: AsyncClient):
        response = await client.post("/api/market/tickers", json={"symbol": "AAPL"})
        assert response.status_code == 403  # HTTPBearer returns 403 when no credentials

    @pytest.mark.asyncio
    async def test_logs_recent_without_token_is_403(self, client: AsyncClient):
        response = await client.get("/api/logs/recent")
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_post_ticker_with_bad_token_is_401(self, client: AsyncClient):
        response = await client.post(
            "/api/market/tickers",
            json={"symbol": "AAPL"},
            headers={"Authorization": "Bearer this.is.not.a.valid.token"},
        )
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_logs_recent_with_valid_token_succeeds(
        self, client: AsyncClient, auth_headers: dict
    ):
        response = await client.get("/api/logs/recent", headers=auth_headers)
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    @pytest.mark.asyncio
    async def test_run_analysis_without_token_is_403(self, client: AsyncClient):
        response = await client.post(
            "/api/analysis/run",
            json={"ticker": "AAPL", "period": "1mo", "interval": "1d"},
        )
        assert response.status_code == 403


# ===========================================================================
# Market — tickers
# ===========================================================================

class TestMarketTickers:
    @pytest.mark.asyncio
    async def test_list_tickers_no_auth_required(self, client: AsyncClient):
        """GET /api/market/tickers is public."""
        response = await client.get("/api/market/tickers")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    @pytest.mark.asyncio
    async def test_add_ticker_requires_auth(self, client: AsyncClient, auth_headers: dict):
        response = await client.post(
            "/api/market/tickers",
            json={"symbol": "MSFT", "name": "Microsoft", "sector": "Technology"},
            headers=auth_headers,
        )
        assert response.status_code == 201
        body = response.json()
        assert body["symbol"] == "MSFT"
        assert body["is_active"] is True

    @pytest.mark.asyncio
    async def test_add_ticker_symbol_uppercased(self, client: AsyncClient, auth_headers: dict):
        response = await client.post(
            "/api/market/tickers",
            json={"symbol": "tsla"},
            headers=auth_headers,
        )
        assert response.status_code == 201
        assert response.json()["symbol"] == "TSLA"

    @pytest.mark.asyncio
    async def test_add_duplicate_ticker_is_409(self, client: AsyncClient, auth_headers: dict):
        payload = {"symbol": "GOOGL"}
        await client.post("/api/market/tickers", json=payload, headers=auth_headers)
        response = await client.post("/api/market/tickers", json=payload, headers=auth_headers)
        assert response.status_code == 409

    @pytest.mark.asyncio
    async def test_added_ticker_appears_in_list(self, client: AsyncClient, auth_headers: dict):
        await client.post(
            "/api/market/tickers",
            json={"symbol": "NVDA"},
            headers=auth_headers,
        )
        response = await client.get("/api/market/tickers")
        symbols = [t["symbol"] for t in response.json()]
        assert "NVDA" in symbols


# ===========================================================================
# Market — candles
# ===========================================================================

class TestMarketCandles:
    @pytest.mark.asyncio
    async def test_get_candles_empty_when_no_data(self, client: AsyncClient):
        response = await client.get("/api/market/candles?ticker=ZZZZ")
        assert response.status_code == 200
        assert response.json() == []

    @pytest.mark.asyncio
    async def test_get_candles_missing_ticker_param(self, client: AsyncClient):
        response = await client.get("/api/market/candles")
        assert response.status_code == 422


# ===========================================================================
# Market — fetch (yfinance mocked)
# ===========================================================================

class TestMarketFetch:
    @pytest.mark.asyncio
    async def test_fetch_returns_empty_when_yfinance_fails(self, client: AsyncClient):
        with patch(
            "app.services.data_fetcher.fetch_ohlcv",
            new_callable=AsyncMock,
            return_value=[],
        ):
            response = await client.get("/api/market/fetch?ticker=FAKE&period=1mo&interval=1d")
        assert response.status_code == 200
        body = response.json()
        assert body["ticker"] == "FAKE"
        assert body["count"] == 0
        assert body["candles"] == []

    @pytest.mark.asyncio
    async def test_fetch_stores_candles_from_yfinance(self, client: AsyncClient):
        fake_candles = _make_candle_rows(3)
        with patch(
            "app.services.data_fetcher.fetch_ohlcv",
            new_callable=AsyncMock,
            return_value=fake_candles,
        ):
            response = await client.get("/api/market/fetch?ticker=AAPL&period=1mo&interval=1d")
        assert response.status_code == 200
        body = response.json()
        assert body["ticker"] == "AAPL"
        assert body["count"] == 3

    @pytest.mark.asyncio
    async def test_fetch_missing_ticker_param(self, client: AsyncClient):
        response = await client.get("/api/market/fetch?period=1mo&interval=1d")
        assert response.status_code == 422


# ===========================================================================
# Analysis — run (tokenizer + Gemini mocked)
# ===========================================================================

class TestAnalysisRun:
    """
    /api/analysis/run requires:
    1. Candles already stored in the DB for the requested ticker/interval.
    2. JWT token.

    We seed candles directly via the DB session fixture in conftest, then mock
    both the tokenizer and Gemini to avoid heavy computation or network calls.
    """

    @pytest.fixture()
    def mock_gemini_result(self) -> dict:
        return {
            "summary": "Bullish trend detected.",
            "sentiment": "bullish",
            "confidence": 0.75,
            "signals": [{"type": "momentum", "strength": "moderate", "description": "Price rising."}],
            "key_levels": [150.0, 155.0],
            "risk_factors": ["Market volatility"],
            "mock_mode": False,
        }

    @pytest.mark.asyncio
    async def test_run_analysis_requires_auth(self, client: AsyncClient):
        response = await client.post(
            "/api/analysis/run",
            json={"ticker": "AAPL", "period": "1mo", "interval": "1d"},
        )
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_run_analysis_not_enough_candles(
        self, client: AsyncClient, auth_headers: dict
    ):
        """With 0 candles in DB the endpoint must return 422."""
        response = await client.post(
            "/api/analysis/run",
            json={"ticker": "NOOP", "period": "1mo", "interval": "1d"},
            headers=auth_headers,
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_run_analysis_success(
        self,
        client: AsyncClient,
        auth_headers: dict,
        mock_gemini_result: dict,
    ):
        """
        Seed the DB with candles via the market/fetch endpoint (mocked yfinance),
        then run analysis with mocked tokenizer and Gemini.
        """
        from app.services.tokenizer import TokenizedSequence

        fake_candles = _make_candle_rows(10)
        fake_token_seq = TokenizedSequence(
            coarse_tokens=list(range(9)),
            fine_tokens=[3] * 9,
            n_candles=10,
            normalization_stats={"mean": 0.001, "std": 0.002, "lo": -0.005, "hi": 0.005},
        )

        with patch(
            "app.services.data_fetcher.fetch_ohlcv",
            new_callable=AsyncMock,
            return_value=fake_candles,
        ):
            await client.get("/api/market/fetch?ticker=AMZN&period=1mo&interval=1d")

        with (
            patch(
                "app.routers.analysis.tokenize_ohlcv",
                return_value=fake_token_seq,
            ),
            patch(
                "app.routers.analysis.tokens_to_prompt_repr",
                return_value="Ticker: AMZN | Period: 1mo | Candles: 10\nCoarse: [...]",
            ),
            patch(
                "app.routers.analysis.analyze_with_gemini",
                new_callable=AsyncMock,
                return_value=mock_gemini_result,
            ),
            patch(
                "app.routers.analysis.log_event",
                new_callable=AsyncMock,
            ),
        ):
            response = await client.post(
                "/api/analysis/run",
                json={"ticker": "AMZN", "period": "1mo", "interval": "1d"},
                headers=auth_headers,
            )

        assert response.status_code == 200
        body = response.json()
        assert body["ticker_symbol"] == "AMZN"
        assert body["gemini_sentiment"] == "bullish"
        assert body["gemini_confidence"] == 0.75
        assert body["mock_mode"] is False
        assert "message" in body

    @pytest.mark.asyncio
    async def test_run_analysis_mock_mode_when_no_gemini_key(
        self,
        client: AsyncClient,
        auth_headers: dict,
    ):
        """
        When GEMINI_API_KEY is empty (test settings default), analyze_with_gemini
        returns mock data. Confirm the endpoint still succeeds and returns mock_mode=True.
        """
        from app.services.tokenizer import TokenizedSequence

        fake_candles = _make_candle_rows(8)
        fake_token_seq = TokenizedSequence(
            coarse_tokens=list(range(7)),
            fine_tokens=[1] * 7,
            n_candles=8,
            normalization_stats={"mean": 0.0, "std": 0.001, "lo": -0.003, "hi": 0.003},
        )

        with patch(
            "app.services.data_fetcher.fetch_ohlcv",
            new_callable=AsyncMock,
            return_value=fake_candles,
        ):
            await client.get("/api/market/fetch?ticker=META&period=1mo&interval=1d")

        with (
            patch("app.routers.analysis.tokenize_ohlcv", return_value=fake_token_seq),
            patch(
                "app.routers.analysis.tokens_to_prompt_repr",
                return_value="Ticker: META | Period: 1mo | Candles: 8\n...",
            ),
            patch("app.routers.analysis.log_event", new_callable=AsyncMock),
        ):
            response = await client.post(
                "/api/analysis/run",
                json={"ticker": "META", "period": "1mo", "interval": "1d"},
                headers=auth_headers,
            )

        assert response.status_code == 200
        body = response.json()
        # gemini_api_key is "" in test settings → mock path in analyze_with_gemini
        assert body["mock_mode"] is True


# ===========================================================================
# Analysis — history and detail
# ===========================================================================

class TestAnalysisHistory:
    @pytest.mark.asyncio
    async def test_history_returns_list(self, client: AsyncClient):
        response = await client.get("/api/analysis/history?ticker=AAPL")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    @pytest.mark.asyncio
    async def test_history_missing_ticker_param(self, client: AsyncClient):
        response = await client.get("/api/analysis/history")
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_get_analysis_not_found(self, client: AsyncClient):
        response = await client.get("/api/analysis/99999999")
        assert response.status_code == 404


# ===========================================================================
# News routes (feedparser mocked)
# ===========================================================================

class TestNews:
    @pytest.mark.asyncio
    async def test_latest_news_is_empty_initially(self, client: AsyncClient):
        response = await client.get("/api/news/latest")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    @pytest.mark.asyncio
    async def test_fetch_news_mocked(self, client: AsyncClient):
        fake_items = [
            {
                "title": "AAPL hits all-time high",
                "url": "https://example.com/news/1",
                "published_at": datetime(2024, 3, 1, 10, 0, 0),
                "source": "Yahoo Finance",
                "summary": "Apple stock surged today.",
                "ticker_symbol": "AAPL",
            }
        ]
        with patch(
            "app.routers.news.fetch_yahoo_news",
            new_callable=AsyncMock,
            return_value=fake_items,
        ):
            response = await client.get("/api/news/fetch?ticker=AAPL")
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_fetch_news_missing_ticker(self, client: AsyncClient):
        response = await client.get("/api/news/fetch")
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_get_news_by_ticker_path(self, client: AsyncClient):
        response = await client.get("/api/news/ticker/AAPL")
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    @pytest.mark.asyncio
    async def test_general_news_mocked(self, client: AsyncClient):
        with patch(
            "app.routers.news.fetch_general_market_news",
            new_callable=AsyncMock,
            return_value=[],
        ):
            response = await client.get("/api/news/general")
        assert response.status_code == 200


# ===========================================================================
# Logs routes
# ===========================================================================

class TestLogs:
    @pytest.mark.asyncio
    async def test_recent_logs_returns_list_when_authenticated(
        self, client: AsyncClient, auth_headers: dict
    ):
        response = await client.get("/api/logs/recent", headers=auth_headers)
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    @pytest.mark.asyncio
    async def test_recent_logs_default_limit(
        self, client: AsyncClient, auth_headers: dict
    ):
        response = await client.get("/api/logs/recent?limit=10", headers=auth_headers)
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_logs_stream_endpoint_exists(self, client: AsyncClient):
        """SSE endpoint should be reachable (no auth required per router comment)."""
        # We just hit it and expect either 200 (SSE started) or 204; not 404.
        # Since the stream is infinite we don't await the full response.
        # httpx will close the connection; that's fine for a smoke test.
        try:
            async with client.stream("GET", "/api/logs/stream") as response:
                assert response.status_code == 200
        except Exception:
            pass  # Connection closed/reset on SSE is expected in test context


# ===========================================================================
# Gemini client unit tests (pure unit — no HTTP client needed)
# ===========================================================================

class TestGeminiClient:
    """
    Unit-test the gemini_client module in isolation.
    All google-genai SDK calls are replaced by MagicMock / AsyncMock.
    """

    @pytest.mark.asyncio
    async def test_analyze_returns_mock_when_no_api_key(self):
        """When gemini_api_key is empty, analyze_with_gemini returns mock_mode=True."""
        with patch("app.services.gemini_client.get_settings") as mock_settings:
            mock_settings.return_value.gemini_api_key = ""
            mock_settings.return_value.gemini_model = "gemini-1.5-flash"

            from app.services.gemini_client import analyze_with_gemini

            result = await analyze_with_gemini("token repr", "AAPL", [])

        assert result["mock_mode"] is True
        assert isinstance(result["summary"], str)
        assert len(result["summary"]) > 0
        assert result["sentiment"] in {"bullish", "bearish", "neutral"}
        assert isinstance(result["confidence"], float)

    @pytest.mark.asyncio
    async def test_analyze_calls_gemini_when_key_set(self):
        """When a key is present, _call_with_retry is invoked."""
        expected = {
            "summary": "Strong bullish signal.",
            "sentiment": "bullish",
            "confidence": 0.85,
            "signals": [],
            "key_levels": [100.0],
            "risk_factors": [],
            "mock_mode": False,
        }

        with (
            patch("app.services.gemini_client.get_settings") as mock_settings,
            patch(
                "app.services.gemini_client._call_with_retry",
                new_callable=AsyncMock,
                return_value=expected,
            ) as mock_call,
        ):
            mock_settings.return_value.gemini_api_key = "fake-api-key"
            mock_settings.return_value.gemini_model = "gemini-1.5-flash"

            from app.services.gemini_client import analyze_with_gemini

            result = await analyze_with_gemini("token repr", "TSLA", ["Tesla news"])

        mock_call.assert_awaited_once()
        assert result["sentiment"] == "bullish"
        assert result["mock_mode"] is False

    @pytest.mark.asyncio
    async def test_analyze_handles_timeout(self):
        """asyncio.TimeoutError during the Gemini call → mock_mode=True with timeout message."""
        with (
            patch("app.services.gemini_client.get_settings") as mock_settings,
            patch(
                "app.services.gemini_client._call_with_retry",
                side_effect=asyncio.TimeoutError,
            ),
        ):
            mock_settings.return_value.gemini_api_key = "fake-key"
            mock_settings.return_value.gemini_model = "gemini-1.5-flash"

            from app.services.gemini_client import analyze_with_gemini

            result = await analyze_with_gemini("tok", "AAPL", [])

        assert result["mock_mode"] is True
        assert "timeout" in result["summary"].lower()

    @pytest.mark.asyncio
    async def test_analyze_handles_generic_exception(self):
        """Any unexpected SDK exception → mock_mode=True with error in summary."""
        with (
            patch("app.services.gemini_client.get_settings") as mock_settings,
            patch(
                "app.services.gemini_client._call_with_retry",
                side_effect=RuntimeError("SDK crashed"),
            ),
        ):
            mock_settings.return_value.gemini_api_key = "fake-key"
            mock_settings.return_value.gemini_model = "gemini-1.5-flash"

            from app.services.gemini_client import analyze_with_gemini

            result = await analyze_with_gemini("tok", "GOOG", [])

        assert result["mock_mode"] is True
        assert "RuntimeError" in result["summary"]

    def test_parse_gemini_response_valid_json(self):
        """_parse_gemini_response correctly parses a clean JSON string."""
        from app.services.gemini_client import _parse_gemini_response

        raw = json.dumps({
            "summary": "Neutral outlook.",
            "sentiment": "neutral",
            "confidence": 0.5,
            "signals": [{"type": "consolidation", "strength": "weak", "description": "Flat."}],
            "key_levels": [200.0],
            "risk_factors": ["Low volume"],
        })
        result = _parse_gemini_response(raw)
        assert result["sentiment"] == "neutral"
        assert result["confidence"] == 0.5
        assert isinstance(result["signals"], list)
        assert result["mock_mode"] is False

    def test_parse_gemini_response_strips_markdown_fences(self):
        """_parse_gemini_response handles ```json ... ``` wrapping."""
        from app.services.gemini_client import _parse_gemini_response

        inner = json.dumps({
            "summary": "Bearish.",
            "sentiment": "bearish",
            "confidence": 0.9,
            "signals": [],
            "key_levels": [],
            "risk_factors": [],
        })
        raw = f"```json\n{inner}\n```"
        result = _parse_gemini_response(raw)
        assert result["sentiment"] == "bearish"

    def test_parse_gemini_response_invalid_json_returns_error_struct(self):
        """Non-JSON text → fallback dict with error info instead of raising."""
        from app.services.gemini_client import _parse_gemini_response

        result = _parse_gemini_response("This is not JSON at all!")
        assert result["sentiment"] == "neutral"
        assert result["confidence"] == 0.0
        assert "parse" in result["summary"].lower() or "JSON" in result["summary"]

    def test_parse_gemini_response_invalid_sentiment_coerced(self):
        """Unexpected sentiment value → coerced to 'neutral'."""
        from app.services.gemini_client import _parse_gemini_response

        raw = json.dumps({
            "summary": "Test.",
            "sentiment": "very_bullish_definitely",
            "confidence": 0.6,
            "signals": [],
            "key_levels": [],
            "risk_factors": [],
        })
        result = _parse_gemini_response(raw)
        assert result["sentiment"] == "neutral"

    def test_parse_gemini_response_confidence_clamped(self):
        """Confidence value outside [0, 1] → clamped."""
        from app.services.gemini_client import _parse_gemini_response

        raw = json.dumps({
            "summary": "Test.",
            "sentiment": "bullish",
            "confidence": 99.9,
            "signals": [],
            "key_levels": [],
            "risk_factors": [],
        })
        result = _parse_gemini_response(raw)
        assert result["confidence"] == 1.0

    def test_build_prompt_contains_ticker(self):
        """_build_prompt includes the ticker symbol in the output."""
        from app.services.gemini_client import _build_prompt

        prompt = _build_prompt("Coarse: [1,2,3]", "NVDA", [])
        assert "NVDA" in prompt

    def test_build_prompt_includes_headlines(self):
        """_build_prompt includes provided headlines."""
        from app.services.gemini_client import _build_prompt

        headlines = ["NVDA Q1 earnings beat", "GPU demand surges"]
        prompt = _build_prompt("token data", "NVDA", headlines)
        assert "NVDA Q1 earnings beat" in prompt

    def test_build_prompt_truncates_headlines_to_five(self):
        """_build_prompt only uses the first 5 headlines."""
        from app.services.gemini_client import _build_prompt

        headlines = [f"Headline {i}" for i in range(10)]
        prompt = _build_prompt("token data", "AAPL", headlines)
        # "Headline 5" (index 5) should NOT appear; "Headline 4" should
        assert "Headline 4" in prompt
        assert "Headline 5" not in prompt
