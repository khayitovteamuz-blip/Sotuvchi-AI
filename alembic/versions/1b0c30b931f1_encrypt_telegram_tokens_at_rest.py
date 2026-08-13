"""encrypt telegram tokens at rest

Widens the two secret columns to fit ciphertext, then encrypts whatever is
already there. A bot token is the shop's entire channel to its customers, so a
database dump used to hand an attacker every business on the platform at once.

Runs only when ENCRYPTION_KEY is configured. Without it the columns are still
widened — so the key can be added later and this migration re-run as a one-off
script — but nothing is rewritten and a warning is printed.

Revision ID: 1b0c30b931f1
Revises: 4f4b53278dfb
Create Date: 2026-08-13 05:04:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = '1b0c30b931f1'
down_revision: Union[str, Sequence[str], None] = '4f4b53278dfb'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

COLUMNS = ("telegram_bot_token", "telegram_webhook_secret")


def upgrade() -> None:
    # Ciphertext is ~4x the plaintext; the old widths (128 and 64) would fail.
    op.alter_column('tenants', 'telegram_bot_token',
                    existing_type=sa.VARCHAR(length=128),
                    type_=sa.String(length=512), existing_nullable=True)
    op.alter_column('tenants', 'telegram_webhook_secret',
                    existing_type=sa.VARCHAR(length=64),
                    type_=sa.String(length=512), existing_nullable=True)

    from app.core import crypto

    if not crypto._cipher():
        print("  ENCRYPTION_KEY yo'q — tokenlar ochiq matnda qoldi. "
              "Kalit qo'shilgach shu migratsiyani qayta bajaring.")
        return

    conn = op.get_bind()
    rows = conn.execute(sa.text(
        "SELECT id, telegram_bot_token, telegram_webhook_secret FROM tenants "
        "WHERE telegram_bot_token IS NOT NULL OR telegram_webhook_secret IS NOT NULL"
    )).fetchall()

    encrypted = 0
    for tenant_id, token, secret in rows:
        values = {"id": tenant_id}
        sets = []
        for column, value in zip(COLUMNS, (token, secret)):
            if value and not crypto.is_encrypted(value):
                values[column] = crypto.encrypt(value)
                sets.append(f"{column} = :{column}")
        if sets:
            conn.execute(
                sa.text(f"UPDATE tenants SET {', '.join(sets)} WHERE id = :id"), values
            )
            encrypted += 1
    print(f"  {encrypted} ta biznesning Telegram sirlari shifrlandi.")


def downgrade() -> None:
    """Decrypt back to plain text before narrowing, or the values are lost."""
    from app.core import crypto

    conn = op.get_bind()
    if crypto._cipher():
        rows = conn.execute(sa.text(
            "SELECT id, telegram_bot_token, telegram_webhook_secret FROM tenants "
            "WHERE telegram_bot_token IS NOT NULL OR telegram_webhook_secret IS NOT NULL"
        )).fetchall()
        for tenant_id, token, secret in rows:
            values = {"id": tenant_id}
            sets = []
            for column, value in zip(COLUMNS, (token, secret)):
                if crypto.is_encrypted(value):
                    values[column] = crypto.decrypt(value)
                    sets.append(f"{column} = :{column}")
            if sets:
                conn.execute(
                    sa.text(f"UPDATE tenants SET {', '.join(sets)} WHERE id = :id"), values
                )

    op.alter_column('tenants', 'telegram_webhook_secret',
                    existing_type=sa.String(length=512),
                    type_=sa.VARCHAR(length=64), existing_nullable=True)
    op.alter_column('tenants', 'telegram_bot_token',
                    existing_type=sa.String(length=512),
                    type_=sa.VARCHAR(length=128), existing_nullable=True)
