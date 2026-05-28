from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Candle(Base):
    __tablename__ = "candles"
    __table_args__ = (
        UniqueConstraint("ticker_symbol", "timestamp", "interval", name="uq_candle_symbol_ts_interval"),
        Index("ix_candle_symbol_ts", "ticker_symbol", "timestamp"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    ticker_id: Mapped[int | None] = mapped_column(ForeignKey("tickers.id", ondelete="SET NULL"), nullable=True)
    ticker_symbol: Mapped[str] = mapped_column(String(20), nullable=False, index=True)
    timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=False), nullable=False, index=True)
    open: Mapped[float] = mapped_column(Float, nullable=False)
    high: Mapped[float] = mapped_column(Float, nullable=False)
    low: Mapped[float] = mapped_column(Float, nullable=False)
    close: Mapped[float] = mapped_column(Float, nullable=False)
    volume: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    interval: Mapped[str] = mapped_column(String(10), nullable=False, default="1d")

    def __repr__(self) -> str:
        return f"<Candle {self.ticker_symbol} {self.timestamp} {self.interval}>"
