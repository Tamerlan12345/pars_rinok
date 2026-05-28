from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Analysis(Base):
    __tablename__ = "analyses"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    ticker_symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    period: Mapped[str] = mapped_column(String(10), nullable=False)
    interval: Mapped[str] = mapped_column(String(10), nullable=False)
    candle_count: Mapped[int] = mapped_column(nullable=False, default=0)
    tokens_coarse: Mapped[list | None] = mapped_column(JSON, nullable=True)
    tokens_fine: Mapped[list | None] = mapped_column(JSON, nullable=True)
    gemini_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    gemini_signals: Mapped[list | None] = mapped_column(JSON, nullable=True)
    gemini_sentiment: Mapped[str | None] = mapped_column(String(20), nullable=True)
    gemini_confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    mock_mode: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=False),
        default=lambda: datetime.utcnow(),
        nullable=False,
        index=True,
    )

    def __repr__(self) -> str:
        return f"<Analysis {self.ticker_symbol} {self.period} {self.created_at}>"
