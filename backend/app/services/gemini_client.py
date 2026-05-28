"""
Gemini API wrapper for financial market analysis.

Runs the blocking google-genai SDK call in a thread-pool executor so the
FastAPI event loop is never blocked. Retries transient errors with exponential
backoff. Falls back to deterministic mock data when GEMINI_API_KEY is absent.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import get_settings

logger = logging.getLogger("centras.gemini")

_SYSTEM_INSTRUCTION = (
    "You are a senior quantitative analyst specializing in financial market "
    "microstructure. Analyze tokenized OHLCV sequences and provide structured "
    "insights about price trends, momentum, and risk."
)

_RESPONSE_SCHEMA_HINT = """\
Respond ONLY with a valid JSON object in exactly this shape — no markdown fences, no explanation:
{
  "summary": "<2-4 sentence analysis>",
  "sentiment": "<bullish|bearish|neutral>",
  "confidence": <float 0.0-1.0>,
  "signals": [
    {"type": "<momentum|reversal|breakout|consolidation>", "strength": "<weak|moderate|strong>", "description": "<1 sentence>"}
  ],
  "key_levels": [<float>, ...],
  "risk_factors": ["<string>", ...]
}"""

_MOCK_RESPONSE: dict[str, Any] = {
    "summary": (
        "Mock analysis: Gemini API key not configured. "
        "The tokenized sequence shows a neutral pattern with moderate volatility. "
        "No actionable signals can be generated without a live model. "
        "Configure GEMINI_API_KEY to enable real analysis."
    ),
    "sentiment": "neutral",
    "confidence": 0.0,
    "signals": [
        {
            "type": "consolidation",
            "strength": "weak",
            "description": "Mock signal — replace with real Gemini output by setting GEMINI_API_KEY.",
        }
    ],
    "key_levels": [],
    "risk_factors": ["GEMINI_API_KEY not configured — analysis is mocked"],
    "mock_mode": True,
}


def _build_prompt(token_repr: str, ticker: str, recent_news: list[str]) -> str:
    news_block = ""
    if recent_news:
        headlines = "\n".join(f"  - {h}" for h in recent_news[:5])
        news_block = f"\nRecent news headlines:\n{headlines}\n"

    return (
        f"Analyze the following tokenized OHLCV data for {ticker}.\n\n"
        f"{token_repr}\n"
        f"{news_block}\n"
        f"{_RESPONSE_SCHEMA_HINT}"
    )


def _call_gemini_sync(prompt: str, model_name: str, api_key: str) -> dict[str, Any]:
    """
    Synchronous Gemini call — intended to run in a thread-pool executor.
    Uses the google-genai SDK which may perform blocking I/O.
    """
    import google.genai as genai  # type: ignore[import-untyped]

    client = genai.Client(api_key=api_key)

    response = client.models.generate_content(
        model=model_name,
        contents=prompt,
        config=genai.types.GenerateContentConfig(
            system_instruction=_SYSTEM_INSTRUCTION,
            temperature=0.2,          # low temperature for deterministic financial output
            max_output_tokens=1024,
        ),
    )

    raw_text: str = response.text or ""
    return _parse_gemini_response(raw_text)


def _parse_gemini_response(raw_text: str) -> dict[str, Any]:
    """
    Extract and validate the JSON payload from Gemini's text response.
    Strips markdown code fences if the model ignores the no-fence instruction.
    """
    cleaned = raw_text.strip()

    # Strip ```json ... ``` fences if present.
    fence_match = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", cleaned)
    if fence_match:
        cleaned = fence_match.group(1).strip()

    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        logger.warning("Gemini returned non-JSON text: %s… (error: %s)", cleaned[:200], exc)
        # Return a best-effort structure rather than raising — the caller will
        # store whatever we return; the summary will make the failure visible.
        return {
            "summary": f"Gemini response could not be parsed as JSON. Raw excerpt: {cleaned[:300]}",
            "sentiment": "neutral",
            "confidence": 0.0,
            "signals": [],
            "key_levels": [],
            "risk_factors": ["Response parse error — see summary"],
            "mock_mode": False,
        }

    # Validate required fields and coerce types.
    sentiment = data.get("sentiment", "neutral")
    if sentiment not in {"bullish", "bearish", "neutral"}:
        sentiment = "neutral"

    confidence = data.get("confidence", 0.0)
    try:
        confidence = max(0.0, min(1.0, float(confidence)))
    except (TypeError, ValueError):
        confidence = 0.0

    signals = data.get("signals", [])
    if not isinstance(signals, list):
        signals = []

    key_levels = data.get("key_levels", [])
    if not isinstance(key_levels, list):
        key_levels = []

    risk_factors = data.get("risk_factors", [])
    if not isinstance(risk_factors, list):
        risk_factors = []

    return {
        "summary": str(data.get("summary", "")),
        "sentiment": sentiment,
        "confidence": confidence,
        "signals": signals,
        "key_levels": key_levels,
        "risk_factors": risk_factors,
        "mock_mode": False,
    }


@retry(
    retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    stop=stop_after_attempt(3),
    reraise=True,
)
async def _call_with_retry(prompt: str, model_name: str, api_key: str) -> dict[str, Any]:
    """Wraps the sync Gemini call with retry logic and thread-pool offloading."""
    loop = asyncio.get_event_loop()
    return await asyncio.wait_for(
        loop.run_in_executor(None, _call_gemini_sync, prompt, model_name, api_key),
        timeout=30.0,
    )


async def analyze_with_gemini(
    token_repr: str,
    ticker: str,
    recent_news: list[str],
) -> dict[str, Any]:
    """
    Request a structured financial analysis from Gemini.

    Returns mock data (mock_mode=True) when GEMINI_API_KEY is not configured,
    so callers always receive a consistent dict shape regardless of API availability.

    Args:
        token_repr: Formatted token string from tokenizer.tokens_to_prompt_repr().
        ticker:     Ticker symbol, used for context in the prompt.
        recent_news: Up to 5 recent headline strings to enrich the prompt.

    Returns:
        dict with keys: summary, sentiment, confidence, signals, key_levels,
                        risk_factors, mock_mode.
    """
    settings = get_settings()

    if not settings.gemini_api_key:
        logger.info("GEMINI_API_KEY not set — returning mock analysis for %s", ticker)
        return dict(_MOCK_RESPONSE)  # copy to prevent mutation of module constant

    prompt = _build_prompt(token_repr, ticker, recent_news)

    try:
        result = await _call_with_retry(prompt, settings.gemini_model, settings.gemini_api_key)
        return result
    except asyncio.TimeoutError:
        logger.error("Gemini request timed out after 30s for ticker %s", ticker)
        return {
            **dict(_MOCK_RESPONSE),
            "summary": "Gemini request timed out. Please retry.",
            "risk_factors": ["Gemini timeout"],
            "mock_mode": True,
        }
    except Exception as exc:  # noqa: BLE001 — all Gemini SDK errors caught here
        logger.error("Gemini API error for %s: %s", ticker, exc, exc_info=True)
        return {
            **dict(_MOCK_RESPONSE),
            "summary": f"Gemini API error: {type(exc).__name__}. Analysis unavailable.",
            "risk_factors": [f"API error: {type(exc).__name__}"],
            "mock_mode": True,
        }
