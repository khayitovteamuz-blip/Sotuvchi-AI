"""platform admin, sessions, plans, audit log

The platform side of the service: the tables the operator uses to run every
business on it. Kept out of the tenant model so a customer-facing bug cannot
reach them.

Revision ID: b3f7a91c204e
Revises: d9e4f27b013c
Create Date: 2026-08-11

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "b3f7a91c204e"
down_revision: Union[str, None] = "d9e4f27b013c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "platform_admins",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("email", sa.String(length=255), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_platform_admins_email"), "platform_admins", ["email"], unique=True)

    op.create_table(
        "platform_sessions",
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("admin_id", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("user_agent", sa.String(length=256), nullable=True),
        sa.ForeignKeyConstraint(["admin_id"], ["platform_admins.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("token_hash"),
    )
    op.create_index(op.f("ix_platform_sessions_admin_id"), "platform_sessions", ["admin_id"])
    op.create_index(op.f("ix_platform_sessions_expires_at"), "platform_sessions", ["expires_at"])

    op.create_table(
        "plans",
        sa.Column("name", sa.String(length=32), nullable=False),
        sa.Column("title", sa.String(length=64), nullable=False),
        sa.Column("price_uzs", sa.Float(), nullable=False, server_default="0"),
        # NULL means unlimited
        sa.Column("max_products", sa.Integer(), nullable=True),
        sa.Column("max_ai_messages_monthly", sa.Integer(), nullable=True),
        sa.Column("max_operators", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("name"),
    )

    op.create_table(
        "platform_audit_log",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("admin_id", sa.String(length=64), nullable=True),
        sa.Column("admin_email", sa.String(length=255), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("tenant_id", sa.String(length=64), nullable=True),
        sa.Column("details", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("ip", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_platform_audit_log_action"), "platform_audit_log", ["action"])
    op.create_index(op.f("ix_platform_audit_log_tenant_id"), "platform_audit_log", ["tenant_id"])
    op.create_index(op.f("ix_platform_audit_log_created_at"), "platform_audit_log", ["created_at"])

    # Seed the three tariffs the app already refers to. Limits are starting
    # points — they are editable from the panel precisely so they need no deploy.
    op.execute(
        """
        INSERT INTO plans (name, title, price_uzs, max_products,
                           max_ai_messages_monthly, max_operators, is_active, sort_order)
        VALUES
            ('start',    'Start',    0,       500,  2000,  1,    true, 1),
            ('business', 'Business', 490000,  5000, 20000, 5,    true, 2),
            ('pro',      'Pro',      1490000, NULL, NULL,  NULL, true, 3)
        ON CONFLICT (name) DO NOTHING
        """
    )

    # The AI-quota check counts this tenant's assistant messages for the current
    # month on every turn; without this index that is a sequential scan.
    op.create_index(
        "ix_messages_tenant_created", "messages", ["tenant_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_messages_tenant_created", table_name="messages")
    op.drop_index(op.f("ix_platform_audit_log_created_at"), table_name="platform_audit_log")
    op.drop_index(op.f("ix_platform_audit_log_tenant_id"), table_name="platform_audit_log")
    op.drop_index(op.f("ix_platform_audit_log_action"), table_name="platform_audit_log")
    op.drop_table("platform_audit_log")
    op.drop_table("plans")
    op.drop_index(op.f("ix_platform_sessions_expires_at"), table_name="platform_sessions")
    op.drop_index(op.f("ix_platform_sessions_admin_id"), table_name="platform_sessions")
    op.drop_table("platform_sessions")
    op.drop_index(op.f("ix_platform_admins_email"), table_name="platform_admins")
    op.drop_table("platform_admins")
