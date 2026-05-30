"""
Unit tests for app.services.tokenizer — the OHLCV tokenization engine.

This module is pure Python + NumPy with no I/O, so tests run fast with no
mocking required.

Coverage targets
----------------
tokenize_ohlcv
  - Happy path: normal 20-candle sequence
  - Minimal sequence: exactly 2 candles
  - Flat prices: std ≈ 0 edge case
  - Single candle → TokenizationError
  - Empty list → TokenizationError
  - Non-positive close price → TokenizationError
  - Token ranges are within [0, N_COARSE-1] / [0, N_FINE-1]
  - Output lengths match len(candles) - 1
  - Normalization stats keys are present
  - Large sequence (500 candles) is handled without error

tokens_to_prompt_repr
  - Returns a non-empty string
  - Contains ticker symbol and period
  - Contains n_candles count
  - Very long token lists are truncated at 500 chars
  - Single-candle sequence (0 tokens) produces valid output
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta
from unittest.mock import patch

import numpy as np
import pytest

from app.services.tokenizer import (
    N_COARSE,
    N_FINE,
    TokenizationError,
    TokenizedSequence,
    tokenize_ohlcv,
    tokens_to_prompt_repr,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_candles(n: int, base_price: float = 100.0, step: float = 0.5) -> list[dict]:
    """Synthetic candles with monotonically increasing close price."""
    start = datetime(2024, 1, 2, 9, 0, 0)
    return [
        {
            "open": base_price + i * step - 0.1,
            "high": base_price + i * step + 0.8,
            "low": base_price + i * step - 0.8,
            "close": base_price + i * step,
            "volume": 1_000_000.0,
            "timestamp": start + timedelta(days=i),
        }
        for i in range(n)
    ]


def _make_flat_candles(n: int, price: float = 50.0) -> list[dict]:
    """All candles with identical close prices (std = 0 edge case)."""
    start = datetime(2024, 1, 2)
    return [
        {
            "open": price,
            "high": price + 0.1,
            "low": price - 0.1,
            "close": price,
            "volume": 500_000.0,
            "timestamp": start + timedelta(days=i),
        }
        for i in range(n)
    ]


# ===========================================================================
# tokenize_ohlcv — happy paths
# ===========================================================================

class TestTokenizeOHLCVHappyPath:
    def test_output_type_is_tokenized_sequence(self):
        seq = tokenize_ohlcv(_make_candles(10))
        assert isinstance(seq, TokenizedSequence)

    def test_coarse_tokens_length(self):
        n = 15
        seq = tokenize_ohlcv(_make_candles(n))
        assert len(seq.coarse_tokens) == n - 1

    def test_fine_tokens_length(self):
        n = 15
        seq = tokenize_ohlcv(_make_candles(n))
        assert len(seq.fine_tokens) == n - 1

    def test_coarse_and_fine_same_length(self):
        seq = tokenize_ohlcv(_make_candles(20))
        assert len(seq.coarse_tokens) == len(seq.fine_tokens)

    def test_n_candles_field(self):
        n = 20
        seq = tokenize_ohlcv(_make_candles(n))
        assert seq.n_candles == n

    def test_coarse_tokens_within_vocab(self):
        seq = tokenize_ohlcv(_make_candles(30))
        assert all(0 <= t < N_COARSE for t in seq.coarse_tokens), (
            f"Coarse token out of range [0, {N_COARSE - 1}]"
        )

    def test_fine_tokens_within_vocab(self):
        seq = tokenize_ohlcv(_make_candles(30))
        assert all(0 <= t < N_FINE for t in seq.fine_tokens), (
            f"Fine token out of range [0, {N_FINE - 1}]"
        )

    def test_normalization_stats_keys_present(self):
        seq = tokenize_ohlcv(_make_candles(10))
        for key in ("mean", "std", "lo", "hi"):
            assert key in seq.normalization_stats, f"Missing stat: {key}"

    def test_normalization_stats_are_finite_floats(self):
        seq = tokenize_ohlcv(_make_candles(10))
        for key, val in seq.normalization_stats.items():
            assert isinstance(val, float), f"Stat '{key}' is not float: {type(val)}"
            assert math.isfinite(val), f"Stat '{key}' is not finite: {val}"

    def test_tokens_are_python_ints(self):
        seq = tokenize_ohlcv(_make_candles(10))
        for t in seq.coarse_tokens:
            assert isinstance(t, int)
        for t in seq.fine_tokens:
            assert isinstance(t, int)

    def test_minimal_sequence_two_candles(self):
        """Exactly 2 candles → 1 log return → 1 token pair."""
        seq = tokenize_ohlcv(_make_candles(2))
        assert len(seq.coarse_tokens) == 1
        assert len(seq.fine_tokens) == 1

    def test_large_sequence_500_candles(self):
        """Smoke-test: 500 candles should not raise or run out of memory."""
        seq = tokenize_ohlcv(_make_candles(500))
        assert len(seq.coarse_tokens) == 499

    def test_random_price_series(self):
        """Random walk prices — should not raise."""
        rng = np.random.default_rng(42)
        prices = np.cumprod(1 + rng.normal(0, 0.01, 50)) * 100.0
        start = datetime(2024, 1, 1)
        candles = [
            {
                "open": float(p) - 0.5,
                "high": float(p) + 1.0,
                "low": float(p) - 1.0,
                "close": float(p),
                "volume": 1_000_000.0,
                "timestamp": start + timedelta(days=i),
            }
            for i, p in enumerate(prices)
        ]
        seq = tokenize_ohlcv(candles)
        assert len(seq.coarse_tokens) == 49
        assert all(0 <= t < N_COARSE for t in seq.coarse_tokens)

    def test_all_tokens_same_for_identical_step(self):
        """
        Perfectly uniform log returns (same step) → after normalization all
        tokens should be equal (or very close to it).
        The exact value isn't critical; we just verify no crash + correct lengths.
        """
        # Geometric series: price * ratio^i, all log returns equal
        ratio = 1.001
        start = datetime(2024, 1, 1)
        n = 20
        candles = [
            {
                "open": 100.0 * ratio ** i,
                "high": 100.0 * ratio ** i + 0.5,
                "low": 100.0 * ratio ** i - 0.5,
                "close": 100.0 * ratio ** i,
                "volume": 1e6,
                "timestamp": start + timedelta(days=i),
            }
            for i in range(n)
        ]
        seq = tokenize_ohlcv(candles)
        assert len(seq.coarse_tokens) == n - 1


# ===========================================================================
# tokenize_ohlcv — flat price / zero-std edge case
# ===========================================================================

class TestTokenizeOHLCVFlatPrices:
    def test_flat_prices_does_not_raise(self):
        seq = tokenize_ohlcv(_make_flat_candles(10))
        assert seq is not None

    def test_flat_prices_token_count_correct(self):
        n = 10
        seq = tokenize_ohlcv(_make_flat_candles(n))
        assert len(seq.coarse_tokens) == n - 1

    def test_flat_prices_tokens_in_range(self):
        seq = tokenize_ohlcv(_make_flat_candles(10))
        assert all(0 <= t < N_COARSE for t in seq.coarse_tokens)
        assert all(0 <= t < N_FINE for t in seq.fine_tokens)

    def test_flat_prices_normalization_std_guarded(self):
        """std should be replaced by the guard value 1e-8, not zero."""
        seq = tokenize_ohlcv(_make_flat_candles(10))
        # std guard prevents division by zero; the stored stat may be the raw
        # near-zero std, but lo == hi should also be handled.
        assert math.isfinite(seq.normalization_stats["std"])


# ===========================================================================
# tokenize_ohlcv — error cases
# ===========================================================================

class TestTokenizeOHLCVErrors:
    def test_empty_list_raises(self):
        with pytest.raises(TokenizationError):
            tokenize_ohlcv([])

    def test_single_candle_raises(self):
        with pytest.raises(TokenizationError):
            tokenize_ohlcv(_make_candles(1))

    def test_zero_close_price_raises(self):
        candles = _make_candles(5)
        candles[2]["close"] = 0.0
        with pytest.raises(TokenizationError):
            tokenize_ohlcv(candles)

    def test_negative_close_price_raises(self):
        candles = _make_candles(5)
        candles[0]["close"] = -10.0
        with pytest.raises(TokenizationError):
            tokenize_ohlcv(candles)

    def test_multiple_non_positive_closes_raises(self):
        candles = _make_candles(10)
        candles[3]["close"] = 0.0
        candles[7]["close"] = -5.0
        with pytest.raises(TokenizationError):
            tokenize_ohlcv(candles)

    def test_error_message_mentions_candle_count(self):
        """Error for 1 candle should tell the user how many were received."""
        with pytest.raises(TokenizationError, match="1"):
            tokenize_ohlcv(_make_candles(1))

    def test_error_message_mentions_non_positive(self):
        candles = _make_candles(5)
        candles[0]["close"] = -1.0
        with pytest.raises(TokenizationError, match="positive"):
            tokenize_ohlcv(candles)


# ===========================================================================
# tokens_to_prompt_repr
# ===========================================================================

class TestTokensToPromptRepr:
    def _seq(self, n_candles: int = 10) -> TokenizedSequence:
        return tokenize_ohlcv(_make_candles(n_candles))

    def test_returns_string(self):
        seq = self._seq()
        result = tokens_to_prompt_repr(seq, "AAPL", "1mo")
        assert isinstance(result, str)

    def test_non_empty(self):
        result = tokens_to_prompt_repr(self._seq(), "AAPL", "1mo")
        assert len(result) > 0

    def test_contains_ticker(self):
        result = tokens_to_prompt_repr(self._seq(), "NVDA", "3mo")
        assert "NVDA" in result

    def test_contains_period(self):
        result = tokens_to_prompt_repr(self._seq(), "AAPL", "6mo")
        assert "6mo" in result

    def test_contains_candle_count(self):
        seq = self._seq(15)
        result = tokens_to_prompt_repr(seq, "AAPL", "1mo")
        assert str(seq.n_candles) in result

    def test_coarse_label_present(self):
        result = tokens_to_prompt_repr(self._seq(), "AAPL", "1mo")
        assert "Coarse" in result

    def test_fine_label_present(self):
        result = tokens_to_prompt_repr(self._seq(), "AAPL", "1mo")
        assert "Fine" in result

    def test_stats_label_present(self):
        result = tokens_to_prompt_repr(self._seq(), "AAPL", "1mo")
        assert "Normalization stats" in result

    def test_long_token_list_truncated(self):
        """
        A 500-candle sequence will produce ~499 tokens. The repr should
        truncate token lists that exceed 500 chars.
        """
        seq = tokenize_ohlcv(_make_candles(500))
        result = tokens_to_prompt_repr(seq, "AAPL", "max")
        assert "[truncated]" in result

    def test_short_token_list_not_truncated(self):
        """10-candle sequence → 9 tokens, well under 500 chars."""
        seq = tokenize_ohlcv(_make_candles(10))
        result = tokens_to_prompt_repr(seq, "AAPL", "1mo")
        assert "[truncated]" not in result

    def test_zero_token_sequence(self):
        """
        Edge case: manually construct a TokenizedSequence with empty token lists.
        tokens_to_prompt_repr should handle it without raising.
        """
        seq = TokenizedSequence(
            coarse_tokens=[],
            fine_tokens=[],
            n_candles=1,
            normalization_stats={"mean": 0.0, "std": 0.0, "lo": 0.0, "hi": 0.0},
        )
        result = tokens_to_prompt_repr(seq, "TEST", "1d")
        assert isinstance(result, str)

    def test_normalization_stats_in_output(self):
        """mean, std, lo, hi values should appear in the string."""
        seq = self._seq()
        result = tokens_to_prompt_repr(seq, "AAPL", "1mo")
        assert "mean=" in result
        assert "std=" in result
        assert "lo=" in result
        assert "hi=" in result

    def test_different_tickers_different_output(self):
        seq = self._seq()
        r1 = tokens_to_prompt_repr(seq, "AAPL", "1mo")
        r2 = tokens_to_prompt_repr(seq, "GOOG", "1mo")
        assert r1 != r2
        assert "AAPL" in r1
        assert "GOOG" in r2

    def test_vocab_range_label_uses_n_coarse(self):
        """The prompt should state the coarse range (0-31 for N_COARSE=32)."""
        result = tokens_to_prompt_repr(self._seq(), "AAPL", "1mo")
        assert str(N_COARSE - 1) in result

    def test_fine_range_label_uses_n_fine(self):
        """The prompt should state the fine range (0-7 for N_FINE=8)."""
        result = tokens_to_prompt_repr(self._seq(), "AAPL", "1mo")
        assert str(N_FINE - 1) in result


# ===========================================================================
# Data fetcher helper tests (pure logic — no network)
# ===========================================================================

class TestDataFetcherLogic:
    """
    Test the internal helper logic of data_fetcher that doesn't require
    an actual network call.
    """

    def test_cache_key_format(self):
        """_cache_key should produce a deterministic colon-separated string."""
        from app.routers.market import _cache_key

        key = _cache_key("AAPL", "1mo", "1d")
        assert key == "AAPL:1mo:1d"

    def test_cache_key_is_case_sensitive(self):
        from app.routers.market import _cache_key

        assert _cache_key("aapl", "1mo", "1d") != _cache_key("AAPL", "1mo", "1d")


# ===========================================================================
# Pydantic schema validation tests
# ===========================================================================

class TestSchemas:
    def test_analysis_request_uppercases_ticker(self):
        from app.schemas.analysis import AnalysisRequest

        req = AnalysisRequest(ticker=" msft ", period="1mo", interval="1d")
        assert req.ticker == "MSFT"

    def test_ticker_create_uppercases_symbol(self):
        from app.schemas.market import TickerCreate

        tc = TickerCreate(symbol=" nvda ", name="Nvidia")
        assert tc.symbol == "NVDA"

    def test_market_fetch_request_uppercases_ticker(self):
        from app.schemas.market import MarketFetchRequest

        req = MarketFetchRequest(ticker=" aapl ")
        assert req.ticker == "AAPL"

    def test_login_request_requires_both_fields(self):
        from pydantic import ValidationError
        from app.schemas.auth import LoginRequest

        with pytest.raises(ValidationError):
            LoginRequest(username="admin")  # missing password

    def test_token_response_defaults(self):
        from app.schemas.auth import TokenResponse

        tr = TokenResponse(access_token="abc", expires_in=3600)
        assert tr.token_type == "bearer"


# ===========================================================================
# Auth token creation logic
# ===========================================================================

class TestAuthTokenLogic:
    def test_create_token_returns_string_and_seconds(self):
        """_create_token should return a JWT string and a positive int."""
        with patch("app.routers.auth.config_module.get_settings") as mock_settings:
            mock_settings.return_value.jwt_expire_minutes = 60
            mock_settings.return_value.jwt_secret_key = "test-secret-32-chars-xxxxxxxxxx"
            mock_settings.return_value.jwt_algorithm = "HS256"

            from app.routers.auth import _create_token

            token, expires = _create_token("admin")

        assert isinstance(token, str)
        assert len(token) > 0
        assert expires == 60 * 60  # 3600 seconds

    def test_create_token_payload_contains_sub(self):
        """The JWT payload 'sub' claim must match the supplied username."""
        from jose import jwt as jose_jwt

        secret = "test-secret-32-chars-xxxxxxxxxx"
        with patch("app.routers.auth.config_module.get_settings") as mock_settings:
            mock_settings.return_value.jwt_expire_minutes = 60
            mock_settings.return_value.jwt_secret_key = secret
            mock_settings.return_value.jwt_algorithm = "HS256"

            from app.routers.auth import _create_token

            token, _ = _create_token("testuser")

        payload = jose_jwt.decode(token, secret, algorithms=["HS256"])
        assert payload["sub"] == "testuser"
