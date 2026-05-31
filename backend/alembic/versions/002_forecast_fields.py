"""Add forecast and extended gemini fields to analyses table.

Revision ID: 002_forecast_fields
Revises: 001_initial
Create Date: 2026-05-31
"""
from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "002_forecast_fields"
down_revision = "001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("analyses", sa.Column("gemini_key_levels", sa.JSON(), nullable=True))
    op.add_column("analyses", sa.Column("gemini_risk_factors", sa.JSON(), nullable=True))
    op.add_column("analyses", sa.Column("forecast_direction", sa.String(10), nullable=True))
    op.add_column("analyses", sa.Column("forecast_price_target", sa.Float(), nullable=True))
    op.add_column("analyses", sa.Column("forecast_period", sa.String(50), nullable=True))
    op.add_column("analyses", sa.Column("forecast_rationale", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("analyses", "forecast_rationale")
    op.drop_column("analyses", "forecast_period")
    op.drop_column("analyses", "forecast_price_target")
    op.drop_column("analyses", "forecast_direction")
    op.drop_column("analyses", "gemini_risk_factors")
    op.drop_column("analyses", "gemini_key_levels")
