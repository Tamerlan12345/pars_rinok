from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, field_validator


class TickerCreate(BaseModel):
    symbol: str
    name: str | None = None
    sector: str | None = None

    @field_validator("symbol", mode="before")
    @classmethod
    def uppercase_symbol(cls, v: str) -> str:
        return v.strip().upper()


class TickerRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    symbol: str
    name: str | None
    sector: str | None
    is_active: bool
    created_at: datetime


class CandleRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticker_symbol: str
    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    interval: str


class MarketFetchRequest(BaseModel):
    ticker: str
    period: str = "1mo"
    interval: str = "1d"

    @field_validator("ticker", mode="before")
    @classmethod
    def uppercase_ticker(cls, v: str) -> str:
        return v.strip().upper()


class MarketFetchResponse(BaseModel):
    ticker: str
    candles: list[CandleRead]
    count: int
    from_cache: bool
