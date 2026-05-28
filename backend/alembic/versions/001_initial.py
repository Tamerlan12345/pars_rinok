"""Initial migration — create all Centras Tokenizer tables.

Revision ID: 001_initial
Revises:
Create Date: 2026-05-28
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "tickers",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("symbol", sa.String(20), nullable=False),
        sa.Column("name", sa.String(200), nullable=True),
        sa.Column("sector", sa.String(100), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("symbol", name="uq_tickers_symbol"),
    )
    op.create_index("ix_tickers_id", "tickers", ["id"])
    op.create_index("ix_tickers_symbol", "tickers", ["symbol"])

    op.create_table(
        "candles",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticker_id", sa.Integer(), nullable=True),
        sa.Column("ticker_symbol", sa.String(20), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("open", sa.Float(), nullable=False),
        sa.Column("high", sa.Float(), nullable=False),
        sa.Column("low", sa.Float(), nullable=False),
        sa.Column("close", sa.Float(), nullable=False),
        sa.Column("volume", sa.Float(), nullable=False, server_default="0"),
        sa.Column("interval", sa.String(10), nullable=False, server_default="1d"),
        sa.ForeignKeyConstraint(["ticker_id"], ["tickers.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("ticker_symbol", "timestamp", "interval", name="uq_candle_symbol_ts_interval"),
    )
    op.create_index("ix_candle_symbol_ts", "candles", ["ticker_symbol", "timestamp"])
    op.create_index("ix_candles_id", "candles", ["id"])

    op.create_table(
        "analyses",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticker_symbol", sa.String(20), nullable=False),
        sa.Column("period", sa.String(10), nullable=False),
        sa.Column("interval", sa.String(10), nullable=False),
        sa.Column("candle_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("tokens_coarse", sa.JSON(), nullable=True),
        sa.Column("tokens_fine", sa.JSON(), nullable=True),
        sa.Column("gemini_summary", sa.Text(), nullable=True),
        sa.Column("gemini_signals", sa.JSON(), nullable=True),
        sa.Column("gemini_sentiment", sa.String(20), nullable=True),
        sa.Column("gemini_confidence", sa.Float(), nullable=True),
        sa.Column("mock_mode", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_analyses_id", "analyses", ["id"])
    op.create_index("ix_analyses_ticker_symbol", "analyses", ["ticker_symbol"])
    op.create_index("ix_analyses_created_at", "analyses", ["created_at"])

    op.create_table(
        "news_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("ticker_symbol", sa.String(20), nullable=True),
        sa.Column("title", sa.String(500), nullable=False),
        sa.Column("url", sa.String(2000), nullable=False),
        sa.Column("published_at", sa.DateTime(), nullable=True),
        sa.Column("source", sa.String(200), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("url", name="uq_news_url"),
    )
    op.create_index("ix_news_items_id", "news_items", ["id"])
    op.create_index("ix_news_items_ticker_symbol", "news_items", ["ticker_symbol"])
    op.create_index("ix_news_items_published_at", "news_items", ["published_at"])

    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("level", sa.String(10), nullable=False, server_default="INFO"),
        sa.Column("event", sa.String(100), nullable=False),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("context", sa.JSON(), nullable=True),
        sa.Column("request_id", sa.String(36), nullable=True),
        sa.Column("user_agent", sa.String(500), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_audit_logs_id", "audit_logs", ["id"])
    op.create_index("ix_audit_logs_timestamp", "audit_logs", ["timestamp"])
    op.create_index("ix_audit_logs_level", "audit_logs", ["level"])
    op.create_index("ix_audit_logs_event", "audit_logs", ["event"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("news_items")
    op.drop_table("analyses")
    op.drop_table("candles")
    op.drop_table("tickers")
