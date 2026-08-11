"""login throttling moves into the database

Per-process counters gave an attacker MAX_ATTEMPTS per worker and lost every
lockout on restart.

Revision ID: c5d82e14f6a9
Revises: a7c31f8d90b4
Create Date: 2026-08-11

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c5d82e14f6a9"
down_revision: Union[str, None] = "a7c31f8d90b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "login_attempts",
        sa.Column("key", sa.String(length=255), nullable=False),  # "ip|email"
        sa.Column("fail_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("key"),
    )
    # The stale-row sweep filters on this
    op.create_index(op.f("ix_login_attempts_window_start"), "login_attempts", ["window_start"])


def downgrade() -> None:
    op.drop_index(op.f("ix_login_attempts_window_start"), table_name="login_attempts")
    op.drop_table("login_attempts")
