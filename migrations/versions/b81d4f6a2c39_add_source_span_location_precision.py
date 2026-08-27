"""add source_spans location-precision columns (defect 3.7, v0.2.1)

Revision ID: b81d4f6a2c39
Revises: e7d2a91c5b48
Create Date: 2026-08-22 10:00:00.000000

Full page range + machine-verifiable location data on every source span:
``page_start``/``page_end`` (interval), ``bounding_boxes`` (JSON, coordinate
system included), and ``precision`` — derived at pipeline time from the stored
fields (never caller-asserted) so provenance claims are checkable downstream.
All columns are additive; existing rows backfill to NULL / '[]' / 'unknown'.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b81d4f6a2c39"
down_revision: str | None = "e7d2a91c5b48"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("source_spans", sa.Column("page_start", sa.Integer(), nullable=True))
    op.add_column("source_spans", sa.Column("page_end", sa.Integer(), nullable=True))
    op.add_column(
        "source_spans",
        sa.Column("bounding_boxes", sa.JSON(), nullable=False, server_default="[]"),
    )
    op.add_column(
        "source_spans",
        sa.Column("precision", sa.String(length=32), nullable=False, server_default="unknown"),
    )


def downgrade() -> None:
    op.drop_column("source_spans", "precision")
    op.drop_column("source_spans", "bounding_boxes")
    op.drop_column("source_spans", "page_end")
    op.drop_column("source_spans", "page_start")
