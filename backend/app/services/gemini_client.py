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
    "Ты — старший квантитативный аналитик, специализирующийся на анализе финансовых рынков. "
    "Твоя задача — анализировать токенизированные последовательности OHLCV и предоставлять "
    "структурированный прогноз с детальными пояснениями. "
    "ОБЯЗАТЕЛЬНО: отвечай ТОЛЬКО на русском языке. "
    "Все текстовые поля (summary, description, forecast_rationale, risk_factors, signals) "
    "должны быть на русском языке."
)

_RESPONSE_SCHEMA_HINT = """\
Ответь ТОЛЬКО валидным JSON-объектом в точно таком формате — без markdown-разметки, без пояснений вне JSON:
{
  "summary": "<2-4 предложения: общий анализ текущей ситуации на русском языке>",
  "sentiment": "<bullish|bearish|neutral>",
  "confidence": <float 0.0-1.0>,
  "signals": [
    {"type": "<momentum|reversal|breakout|consolidation>", "strength": "<weak|moderate|strong>", "description": "<1 предложение на русском>"}
  ],
  "key_levels": [<float>, ...],
  "risk_factors": ["<фактор риска на русском>", ...],
  "forecast_direction": "<up|down|sideways>",
  "forecast_price_target": <float или null>,
  "forecast_period": "<описание периода прогноза, например: '1 месяц', '3 месяца'>",
  "forecast_rationale": "<2-3 предложения: обоснование прогноза на русском языке, с конкретными уровнями и причинами>"
}"""

_MOCK_RESPONSE: dict[str, Any] = {
    "summary": (
        "Демо-режим: ключ GEMINI_API_KEY не настроен. "
        "Токенизированная последовательность демонстрирует нейтральный паттерн с умеренной волатильностью. "
        "Для получения реального анализа необходимо настроить GEMINI_API_KEY в переменных окружения."
    ),
    "sentiment": "neutral",
    "confidence": 0.0,
    "signals": [
        {
            "type": "consolidation",
            "strength": "weak",
            "description": "Демо-сигнал — настройте GEMINI_API_KEY для получения реального анализа.",
        }
    ],
    "key_levels": [],
    "risk_factors": ["GEMINI_API_KEY не настроен — анализ работает в демо-режиме"],
    "forecast_direction": "sideways",
    "forecast_price_target": None,
    "forecast_period": "—",
    "forecast_rationale": "Прогноз недоступен в демо-режиме. Настройте GEMINI_API_KEY для получения реального прогноза на основе токенизированных данных.",
    "mock_mode": True,
}


def _build_prompt(token_repr: str, ticker: str, recent_news: list[str], period: str = "3mo") -> str:
    news_block = ""
    if recent_news:
        headlines = "\n".join(f"  - {h}" for h in recent_news[:5])
        news_block = f"\nПоследние новости по инструменту:\n{headlines}\n"

    # Map API period codes to human-readable Russian labels for the forecast horizon
    period_map = {
        "1d": "1 день", "5d": "5 дней", "1mo": "1 месяц",
        "3mo": "3 месяца", "6mo": "6 месяцев", "1y": "1 год",
    }
    horizon = period_map.get(period, period)

    return (
        f"Проанализируй токенизированные данные OHLCV для инструмента {ticker} "
        f"за период {horizon}.\n\n"
        f"{token_repr}\n"
        f"{news_block}\n"
        f"На основе этих данных:\n"
        f"1. Дай детальный анализ текущей ситуации.\n"
        f"2. Определи ключевые торговые сигналы.\n"
        f"3. Составь прогноз движения цены на следующий период ({horizon}) "
        f"с указанием целевого уровня цены (forecast_price_target) и обоснованием.\n\n"
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
        return {
            "summary": f"Ошибка разбора ответа Gemini. Фрагмент: {cleaned[:300]}",
            "sentiment": "neutral",
            "confidence": 0.0,
            "signals": [],
            "key_levels": [],
            "risk_factors": ["Ошибка разбора JSON — см. поле summary"],
            "forecast_direction": "sideways",
            "forecast_price_target": None,
            "forecast_period": "—",
            "forecast_rationale": "Прогноз недоступен из-за ошибки разбора ответа модели.",
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

    # Forecast fields — gracefully default if model omits them
    forecast_direction = data.get("forecast_direction", "sideways")
    if forecast_direction not in {"up", "down", "sideways"}:
        forecast_direction = "sideways"

    forecast_price_target = data.get("forecast_price_target")
    if forecast_price_target is not None:
        try:
            forecast_price_target = float(forecast_price_target)
        except (TypeError, ValueError):
            forecast_price_target = None

    return {
        "summary": str(data.get("summary", "")),
        "sentiment": sentiment,
        "confidence": confidence,
        "signals": signals,
        "key_levels": key_levels,
        "risk_factors": risk_factors,
        "forecast_direction": forecast_direction,
        "forecast_price_target": forecast_price_target,
        "forecast_period": str(data.get("forecast_period", "—")),
        "forecast_rationale": str(data.get("forecast_rationale", "")),
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
    period: str = "3mo",
) -> dict[str, Any]:
    """
    Request a structured financial analysis from Gemini (Russian language output).

    Returns mock data (mock_mode=True) when GEMINI_API_KEY is not configured,
    so callers always receive a consistent dict shape regardless of API availability.

    Args:
        token_repr:   Formatted token string from tokenizer.tokens_to_prompt_repr().
        ticker:       Ticker symbol, used for context in the prompt.
        recent_news:  Up to 5 recent headline strings to enrich the prompt.
        period:       Data period (e.g. '3mo') — used to set the forecast horizon.

    Returns:
        dict with keys: summary, sentiment, confidence, signals, key_levels,
                        risk_factors, forecast_direction, forecast_price_target,
                        forecast_period, forecast_rationale, mock_mode.
    """
    settings = get_settings()

    if not settings.gemini_api_key:
        logger.info("GEMINI_API_KEY not set — returning mock analysis for %s", ticker)
        return dict(_MOCK_RESPONSE)  # copy to prevent mutation of module constant

    prompt = _build_prompt(token_repr, ticker, recent_news, period=period)

    try:
        result = await _call_with_retry(prompt, settings.gemini_model, settings.gemini_api_key)
        return result
    except asyncio.TimeoutError:
        logger.error("Gemini request timed out after 30s for ticker %s", ticker)
        return {
            **dict(_MOCK_RESPONSE),
            "summary": "Превышено время ожидания ответа Gemini. Попробуйте ещё раз.",
            "risk_factors": ["Таймаут Gemini API"],
            "mock_mode": True,
        }
    except Exception as exc:  # noqa: BLE001 — all Gemini SDK errors caught here
        logger.error("Gemini API error for %s: %s", ticker, exc, exc_info=True)
        return {
            **dict(_MOCK_RESPONSE),
            "summary": f"Ошибка Gemini API: {type(exc).__name__}. Анализ недоступен.",
            "risk_factors": [f"Ошибка API: {type(exc).__name__}"],
            "mock_mode": True,
        }
