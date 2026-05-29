"""
analysis_routes.py — Flask Blueprint for Kronos Gemini AI analysis endpoint.

Registers the ``POST /api/analyze`` route which accepts Kronos forecast results
and returns a Gemini-powered natural-language market analysis.

Usage
-----
In your Flask application factory::

    from webui.analysis_routes import analysis_bp
    app.register_blueprint(analysis_bp)

Required packages::

    pip install flask flask-jwt-extended google-generativeai

Environment variables
---------------------
    GEMINI_API_KEY   — Google Gemini API key.  If absent, the endpoint returns
                       a mock analysis with a helpful error message instead of
                       failing with HTTP 500.
    JWT_SECRET_KEY   — Secret used to sign/verify JWT tokens.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from flask import Blueprint, jsonify, request
from flask_jwt_extended import jwt_required

try:
    from webui.gemini import GEMINI_AVAILABLE, GeminiAnalyst, _MODEL_NAME  # type: ignore[import]
except ImportError:
    from gemini import GEMINI_AVAILABLE, GeminiAnalyst, _MODEL_NAME  # type: ignore[import]

logger = logging.getLogger("kronos.analysis_routes")

# ---------------------------------------------------------------------------
# Blueprint definition
# ---------------------------------------------------------------------------
analysis_bp = Blueprint("analysis", __name__)

# ---------------------------------------------------------------------------
# Shared analyst instance (created lazily per request so the app factory does
# not need the API key at import time)
# ---------------------------------------------------------------------------
_analyst: GeminiAnalyst | None = None


def _get_analyst() -> GeminiAnalyst:
    """Return a module-level cached GeminiAnalyst, re-creating if not yet set."""
    global _analyst  # noqa: PLW0603 — intentional module-level singleton
    if _analyst is None:
        api_key = os.environ.get("GEMINI_API_KEY", "")
        _analyst = GeminiAnalyst(api_key=api_key)
    return _analyst


# ---------------------------------------------------------------------------
# Endpoint helpers
# ---------------------------------------------------------------------------

def _validate_candle_list(value: Any, field_name: str) -> list[dict]:
    """
    Validate that *value* is a non-empty list of dicts.

    Returns the coerced list or raises ``ValueError`` with a descriptive message.
    """
    if not isinstance(value, list):
        raise ValueError(f"'{field_name}' must be a JSON array of OHLCV objects")
    if len(value) == 0:
        raise ValueError(f"'{field_name}' must not be empty")
    if not all(isinstance(item, dict) for item in value):
        raise ValueError(f"Each element of '{field_name}' must be a JSON object")
    return value  # type: ignore[return-value]


# ---------------------------------------------------------------------------
# POST /api/analyze
# ---------------------------------------------------------------------------

@analysis_bp.route("/api/analyze", methods=["POST"])
@jwt_required()
def analyze() -> tuple[Any, int]:
    """
    Analyse Kronos prediction output with Gemini AI.

    Request body (JSON)
    -------------------
    {
        "prediction_results": [ {OHLCV candle}, ... ],   // required
        "actual_data":        [ {OHLCV candle}, ... ],   // optional
        "historical_data":    [ {OHLCV candle}, ... ],   // optional (last 5 used)
        "symbol":             "BTC/USDT"                  // optional, default "Asset"
    }

    Successful response (200)
    -------------------------
    {
        "analysis":  "<natural-language text from Gemini>",
        "model":     "gemini-3.1-flash-lite",
        "mock_mode": false
    }

    Error response (4xx / 5xx)
    --------------------------
    {
        "error":   "<human-readable message>",
        "detail":  "<optional technical detail>"
    }

    Authentication
    --------------
    Requires a valid JWT Bearer token in the ``Authorization`` header.
    Obtain a token from your application's ``/api/auth/login`` endpoint.
    """
    # ------------------------------------------------------------------ #
    # 1. Parse and validate request body
    # ------------------------------------------------------------------ #
    if not request.is_json:
        return jsonify({"error": "Content-Type must be application/json"}), 415

    body: dict = request.get_json(force=False, silent=True) or {}

    # Required field
    raw_prediction = body.get("prediction_results")
    if raw_prediction is None:
        return (
            jsonify(
                {
                    "error": "Missing required field: 'prediction_results'",
                    "detail": (
                        "Provide the Kronos model output as a list of OHLCV candle objects, "
                        "e.g. [{\"open\": 100, \"high\": 105, \"low\": 99, \"close\": 103, "
                        "\"volume\": 5000, \"timestamp\": \"2026-05-29\"}]"
                    ),
                }
            ),
            400,
        )

    try:
        prediction_data = _validate_candle_list(raw_prediction, "prediction_results")
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400

    # Optional fields
    raw_actual = body.get("actual_data")
    actual_data: list[dict] = []
    if raw_actual is not None:
        try:
            actual_data = _validate_candle_list(raw_actual, "actual_data")
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400

    raw_historical = body.get("historical_data", [])
    historical_data: list[dict] = raw_historical if isinstance(raw_historical, list) else []

    symbol: str = str(body.get("symbol", "Asset")).strip() or "Asset"

    # ------------------------------------------------------------------ #
    # 2. Gemini availability guard
    # ------------------------------------------------------------------ #
    analyst = _get_analyst()
    is_mock = not bool(os.environ.get("GEMINI_API_KEY", ""))

    if not GEMINI_AVAILABLE and not is_mock:
        # Package missing and a key was somehow forced — surface clearly
        return (
            jsonify(
                {
                    "error": "google-generativeai package is not installed",
                    "detail": "Run: pip install google-generativeai",
                }
            ),
            503,
        )

    # ------------------------------------------------------------------ #
    # 3. Select analysis mode
    #    — If actual_data is provided: comparison (back-test evaluation)
    #    — Otherwise: forward prediction analysis
    # ------------------------------------------------------------------ #
    try:
        if actual_data:
            logger.info(
                "analyze_comparison request: symbol=%s  pred=%d  actual=%d",
                symbol,
                len(prediction_data),
                len(actual_data),
            )
            analysis_text = analyst.analyze_comparison(
                prediction_data=prediction_data,
                actual_data=actual_data,
            )
        else:
            logger.info(
                "analyze_prediction request: symbol=%s  hist=%d  pred=%d",
                symbol,
                len(historical_data),
                len(prediction_data),
            )
            analysis_text = analyst.analyze_prediction(
                historical_data=historical_data,
                prediction_data=prediction_data,
                symbol=symbol,
            )
    except Exception as exc:  # noqa: BLE001
        logger.error("Unhandled error in /api/analyze: %s", exc, exc_info=True)
        return (
            jsonify(
                {
                    "error": "Internal error while calling Gemini",
                    "detail": f"{type(exc).__name__}: {exc}",
                }
            ),
            500,
        )

    # ------------------------------------------------------------------ #
    # 4. Return result
    # ------------------------------------------------------------------ #
    return (
        jsonify(
            {
                "analysis": analysis_text,
                "model": _MODEL_NAME,
                "mock_mode": is_mock,
                "symbol": symbol,
                "candles_analysed": {
                    "prediction": len(prediction_data),
                    "actual": len(actual_data),
                    "historical_context": min(len(historical_data), 5),
                },
            }
        ),
        200,
    )
