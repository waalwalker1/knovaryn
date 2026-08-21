"""add model_calls.result_payload (durable provider-call dedup, spec §11.5)

Revision ID: e7d2a91c5b48
Revises: c41a2b3e4f50
Create Date: 2026-08-21 12:00:00.000000

The recorded provider response for a request fingerprint. A resumed job whose
in-memory call cache is cold is served from this ledger row instead of
re-invoking the paid provider call, and no duplicate cost event is written.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e7d2a91c5b48"
down_revision: str | None = "c41a2b3e4f50"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "model_calls",
        sa.Column("result_payload", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("model_calls", "result_payload")
