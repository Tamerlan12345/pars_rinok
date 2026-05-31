from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, field_validator


class AnalysisRequest(BaseModel):
    ticker: str
    period: str = "1mo"
    interval: str = "1d"
    forecast_horizon: str = "3 месяца"

    @field_validator("ticker", mode="before")
    @classmethod
    def uppercase_ticker(cls, v: str) -> str:
        return v.strip().upper()


class SignalItem(BaseModel):
    type: str
    strength: str
    description: str


class AnalysisRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticker_symbol: str
    period: str
    interval: str
    candle_count: int
    tokens_coarse: list[int] | None
    tokens_fine: list[int] | None
    gemini_summary: str | None
    gemini_signals: list[dict[str, Any]] | None
    gemini_sentiment: str | None
    gemini_confidence: float | None
    gemini_key_levels: list[Any] | None = None
    gemini_risk_factors: list[str] | None = None
    forecast_direction: str | None = None
    forecast_price_target: float | None = None
    forecast_period: str | None = None
    forecast_rationale: str | None = None
    mock_mode: bool
    created_at: datetime


class AnalysisResponse(AnalysisRead):
    message: str = "Analysis complete"

