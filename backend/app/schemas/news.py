from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class NewsItemRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    ticker_symbol: str | None
    title: str
    url: str
    published_at: datetime | None
    source: str | None
    summary: str | None
    fetched_at: datetime
