"""conversation abuse warning and block

Haqoratli muloqot uchun ikki bosqichli chora: birinchi xabarda ogohlantirish,
ikkinchisida blok. Hisoblagich suhbatda turadi — blok shu chatga tegishli va
operator panelidan bekor qilinadi.

Revision ID: a1d5c9e73b28
Revises: e15eef1e9793
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1d5c9e73b28"
down_revision: Union[str, Sequence[str], None] = "e15eef1e9793"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("abuse_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "conversations",
        sa.Column("blocked_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("conversations", "blocked_at")
    op.drop_column("conversations", "abuse_count")
