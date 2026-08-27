"""plan max model tier

Tarif AI model tanlovini cheklaydi: har bir plans qatoriga eng yuqori model
darajasi (lite | flash | pro) qo'shiladi. Operator /boshqaruv panelidan
tenantga shu darajadan qimmatroq modelni saqlay olmaydi
(app/services/ai_models.py: tier_allowed).

Revision ID: 1f952722a5af
Revises: a1d5c9e73b28
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "1f952722a5af"
down_revision: Union[str, Sequence[str], None] = "a1d5c9e73b28"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "plans",
        sa.Column("max_model_tier", sa.String(length=16), nullable=False, server_default="pro"),
    )
    # REJA qarori (2026-08-25): Start -> Flash Lite, Business -> Flash, Pro -> hammasi.
    # Faqat shu uch nomdagi qatorlar bor bo'lsa yangilanadi — boshqa muhitda
    # boshqa tarif nomlari bo'lsa ham migratsiya xato bermaydi.
    op.execute("UPDATE plans SET max_model_tier = 'lite' WHERE name = 'start'")
    op.execute("UPDATE plans SET max_model_tier = 'flash' WHERE name = 'business'")
    op.execute("UPDATE plans SET max_model_tier = 'pro' WHERE name = 'pro'")


def downgrade() -> None:
    op.drop_column("plans", "max_model_tier")
