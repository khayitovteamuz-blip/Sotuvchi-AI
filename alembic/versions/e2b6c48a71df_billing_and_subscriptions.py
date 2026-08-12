"""balance, subscriptions and the payment ledger

Tariffs now expire. Each business carries a balance it tops up (an admin
confirms the transfer arrived), buys a tariff with, and the tariff runs for the
plan's duration. Suspending a business stops that clock instead of spending it.

Revision ID: e2b6c48a71df
Revises: b3f7a91c204e
Create Date: 2026-08-12

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e2b6c48a71df"
down_revision: Union[str, None] = "b3f7a91c204e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("balance", sa.Float(), nullable=False, server_default="0"))
    op.add_column("tenants", sa.Column("subscription_expires_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("tenants", sa.Column("frozen_at", sa.DateTime(timezone=True), nullable=True))

    op.add_column("plans", sa.Column("duration_days", sa.Integer(), nullable=False, server_default="30"))

    op.create_table(
        "payments",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=False),
        sa.Column("amount", sa.Float(), nullable=False),
        sa.Column("kind", sa.String(length=24), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("plan_name", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("confirmed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_by", sa.String(length=255), nullable=True),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_payments_tenant_id"), "payments", ["tenant_id"])
    op.create_index(op.f("ix_payments_status"), "payments", ["status"])
    op.create_index(op.f("ix_payments_created_at"), "payments", ["created_at"])

    # Existing businesses were signed up before tariffs expired. Cutting them
    # off at deploy would be a support incident, so they start with a full
    # period from now.
    op.execute(
        "UPDATE tenants SET subscription_expires_at = now() + interval '30 days' "
        "WHERE subscription_expires_at IS NULL"
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_payments_created_at"), table_name="payments")
    op.drop_index(op.f("ix_payments_status"), table_name="payments")
    op.drop_index(op.f("ix_payments_tenant_id"), table_name="payments")
    op.drop_table("payments")
    op.drop_column("plans", "duration_days")
    op.drop_column("tenants", "frozen_at")
    op.drop_column("tenants", "subscription_expires_at")
    op.drop_column("tenants", "balance")
