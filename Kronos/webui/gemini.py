"""
gemini.py — Gemini AI integration for the Kronos financial forecasting WebUI.

Sends OHLCV prediction results to Google Gemini Flash Lite and returns a
natural-language market analysis.  Designed to slot into a Flask application
as an importable module; the companion ``analysis_routes.py`` registers the
Flask Blueprint that exposes ``POST /api/analyze``.

Dependencies
------------
    pip install google-generativeai flask flask-jwt-extended

Environment
-----------
    GEMINI_API_KEY   — required for live calls; absent → graceful mock response.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

logger = logging.getLogger("kronos.gemini")

# ---------------------------------------------------------------------------
# Availability flag — checked once at import time so callers can gate UI
# ---------------------------------------------------------------------------
try:
    import google.generativeai as genai  # type: ignore[import-untyped]

    GEMINI_AVAILABLE: bool = True
except ImportError:  # pragma: no cover
    GEMINI_AVAILABLE = False
    logger.warning(
        "google-generativeai package not installed.  "
        "Install it with: pip install google-generativeai"
    )

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
_MODEL_NAME = "gemini-3.1-flash-lite"
_MAX_RETRIES = 3
_RETRY_DELAY_BASE = 1.5  # seconds; multiplied by attempt number (linear backoff)

_SYSTEM_PROMPT = (
    "You are a senior quantitative analyst specialising in crypto and equity "
    "markets.  Your task is to analyse OHLCV (Open, High, Low, Close, Volume) "
    "candlestick data produced by the Kronos hierarchical forecasting model and "
    "return a concise, structured, plain-English market assessment.  "
    "Do NOT use markdown code fences.  "
    "Be direct, data-driven, and flag uncertainty where relevant."
)

_MOCK_ANALYSIS = (
    "[MOCK MODE — GEMINI_API_KEY not configured]\n\n"
    "The Kronos model produced a forecast, but live Gemini analysis is "
    "unavailable because no API key is set.  "
    "Set the GEMINI_API_KEY environment variable to enable real AI analysis.\n\n"
    "Placeholder assessment: The prediction data appears structurally valid.  "
    "No actionable signals can be generated in mock mode."
)


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _format_candle(candle: dict[str, Any], index: int) -> str:
    """Return a compact single-line text representation of one OHLCV candle."""
    ts = candle.get("timestamp") or candle.get("date") or candle.get("time") or f"candle_{index}"
    o = candle.get("open", "?")
    h = candle.get("high", "?")
    lo = candle.get("low", "?")
    c = candle.get("close", "?")
    v = candle.get("volume", "?")
    return f"  [{ts}]  O={o}  H={h}  L={lo}  C={c}  V={v}"


def _format_candle_block(candles: list[dict[str, Any]], label: str) -> str:
    """Format a list of candles as a labelled block of text."""
    if not candles:
        return f"{label}: (no data)\n"
    lines = [f"{label} ({len(candles)} candle(s)):"]
    for i, candle in enumerate(candles):
        lines.append(_format_candle(candle, i))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# GeminiAnalyst
# ---------------------------------------------------------------------------

class GeminiAnalyst:
    """
    Wraps the Google Gemini API for Kronos forecast analysis.

    Parameters
    ----------
    api_key:
        Google Gemini API key.  If empty or ``None`` the analyst operates in
        mock mode and returns placeholder text without making any network call.

    Raises
    ------
    RuntimeError
        If ``google-generativeai`` is not installed and a real API key is
        provided (mock mode does not require the package).
    """

    def __init__(self, api_key: str) -> None:
        self._api_key: str = api_key or ""
        self._mock_mode: bool = not bool(self._api_key)

        if not self._mock_mode:
            if not GEMINI_AVAILABLE:
                raise RuntimeError(
                    "google-generativeai is not installed.  "
                    "Run: pip install google-generativeai"
                )
            genai.configure(api_key=self._api_key)
            self._model = genai.GenerativeModel(
                model_name=_MODEL_NAME,
                system_instruction=_SYSTEM_PROMPT,
                generation_config=genai.types.GenerationConfig(
                    temperature=0.25,          # low temperature for deterministic output
                    max_output_tokens=1024,
                ),
            )
            logger.info("GeminiAnalyst initialised with model %s", _MODEL_NAME)
        else:
            self._model = None  # type: ignore[assignment]
            logger.info("GeminiAnalyst running in mock mode (no API key)")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _call_with_retry(self, prompt: str) -> str:
        """
        Send *prompt* to Gemini and return the response text.

        Retries up to ``_MAX_RETRIES`` times on transient errors with a simple
        linear backoff (1.5 s × attempt).

        Raises
        ------
        Exception
            Re-raises the last exception if all attempts fail.
        """
        last_exc: Exception | None = None

        for attempt in range(1, _MAX_RETRIES + 1):
            try:
                response = self._model.generate_content(prompt)
                text: str = response.text or ""
                if not text.strip():
                    raise ValueError("Gemini returned an empty response")
                return text.strip()

            except Exception as exc:  # noqa: BLE001 — catch all transient SDK errors
                last_exc = exc
                if attempt < _MAX_RETRIES:
                    sleep_time = _RETRY_DELAY_BASE * attempt
                    logger.warning(
                        "Gemini call failed (attempt %d/%d): %s — retrying in %.1fs",
                        attempt,
                        _MAX_RETRIES,
                        exc,
                        sleep_time,
                    )
                    time.sleep(sleep_time)
                else:
                    logger.error(
                        "Gemini call failed after %d attempts: %s",
                        _MAX_RETRIES,
                        exc,
                        exc_info=True,
                    )

        raise last_exc  # type: ignore[misc]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def analyze_prediction(
        self,
        historical_data: list[dict],
        prediction_data: list[dict],
        symbol: str = "Asset",
    ) -> str:
        """
        Analyse a Kronos forecast against its historical context.

        Sends the last 5 historical candles and all prediction candles to
        Gemini and returns a natural-language analysis covering:
          - Trend direction (bullish / bearish / sideways)
          - Key price levels (support / resistance)
          - Risk assessment
          - Confidence in the forecast

        Parameters
        ----------
        historical_data:
            List of OHLCV dicts for the historical window.  Only the last 5
            candles are included in the prompt to keep token usage low.
        prediction_data:
            List of OHLCV dicts produced by the Kronos model (future candles).
        symbol:
            Ticker/asset name used for context, e.g. ``"BTC/USDT"``.

        Returns
        -------
        str
            Plain-text analysis from Gemini, or a mock string if the API key
            is absent.
        """
        if self._mock_mode:
            return _MOCK_ANALYSIS

        recent_history = historical_data[-5:] if historical_data else []

        history_block = _format_candle_block(recent_history, "Recent historical candles (last 5)")
        prediction_block = _format_candle_block(prediction_data, "Predicted candles")

        prompt = (
            f"Asset: {symbol}\n\n"
            f"{history_block}\n\n"
            f"{prediction_block}\n\n"
            "Based on the OHLCV data above, provide a structured analysis covering:\n"
            "1. TREND DIRECTION — is the predicted move bullish, bearish, or sideways?\n"
            "2. KEY LEVELS — identify notable support and resistance price levels.\n"
            "3. RISK ASSESSMENT — what are the main risks or uncertainties in this forecast?\n"
            "4. CONFIDENCE — how reliable does this prediction appear given the historical context?\n\n"
            "Keep the response concise (4–8 sentences total).  "
            "Do not repeat the raw numbers verbatim; synthesise them into actionable insights."
        )

        try:
            return self._call_with_retry(prompt)
        except Exception as exc:  # noqa: BLE001
            logger.error("analyze_prediction failed for %s: %s", symbol, exc)
            return (
                f"Gemini analysis unavailable due to an API error ({type(exc).__name__}).  "
                "Please retry or check your API key."
            )

    def analyze_comparison(
        self,
        prediction_data: list[dict],
        actual_data: list[dict],
    ) -> str:
        """
        Compare Kronos predictions against ground-truth actual candles.

        Useful for back-testing and model evaluation dashboards.

        Parameters
        ----------
        prediction_data:
            OHLCV candles as predicted by Kronos.
        actual_data:
            OHLCV candles that actually occurred over the same period.

        Returns
        -------
        str
            Evaluation analysis from Gemini, or a mock string if no API key.
        """
        if self._mock_mode:
            return _MOCK_ANALYSIS

        prediction_block = _format_candle_block(prediction_data, "Kronos predictions")
        actual_block = _format_candle_block(actual_data, "Actual market data")

        prompt = (
            f"{prediction_block}\n\n"
            f"{actual_block}\n\n"
            "Compare the Kronos model predictions to the actual market data above.\n"
            "1. ACCURACY — how closely did the predicted prices match reality?\n"
            "2. DIRECTIONAL CORRECTNESS — did the model correctly predict the trend direction?\n"
            "3. ERROR ANALYSIS — where did the model deviate most and why might that be?\n"
            "4. MODEL VERDICT — overall, does this forecast quality look sufficient for live trading?\n\n"
            "Keep the response concise (4–8 sentences).  "
            "Quantify deviations where possible (e.g. average % error on close price)."
        )

        try:
            return self._call_with_retry(prompt)
        except Exception as exc:  # noqa: BLE001
            logger.error("analyze_comparison failed: %s", exc)
            return (
                f"Gemini comparison unavailable due to an API error ({type(exc).__name__}).  "
                "Please retry or check your API key."
            )


# ---------------------------------------------------------------------------
# Module-level convenience factory (used by analysis_routes.py)
# ---------------------------------------------------------------------------

def get_analyst() -> GeminiAnalyst:
    """
    Return a ``GeminiAnalyst`` instance configured from the environment.

    Reads ``GEMINI_API_KEY`` from the process environment.  If the variable is
    not set, the analyst is initialised in mock mode.
    """
    api_key = os.environ.get("GEMINI_API_KEY", "")
    return GeminiAnalyst(api_key=api_key)
