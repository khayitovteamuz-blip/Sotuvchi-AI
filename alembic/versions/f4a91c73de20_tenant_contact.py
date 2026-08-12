"""owner contact details on the tenant

Support needs to reach the person who runs the shop. That is often not the
person holding the panel login, so the details belong on the business rather
than on the user account.

Revision ID: f4a91c73de20
Revises: e2b6c48a71df
Create Date: 2026-08-12

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f4a91c73de20"
down_revision: Union[str, None] = "e2b6c48a71df"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("owner_name", sa.String(length=255), nullable=True))
    op.add_column("tenants", sa.Column("phone", sa.String(length=64), nullable=True))
    op.add_column("tenants", sa.Column("telegram_contact", sa.String(length=128), nullable=True))
    op.add_column("tenants", sa.Column("address", sa.Text(), nullable=True))
    op.add_column("tenants", sa.Column("contact_note", sa.Text(), nullable=True))


def downgrade() -> None:
    for col in ("contact_note", "address", "telegram_contact", "phone", "owner_name"):
        op.drop_column("tenants", col)
