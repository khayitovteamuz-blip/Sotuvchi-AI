"""drop the duplicate new-order alert

"Yangi buyurtma" and the order receipt fired one line apart on the same order,
so every sale produced two notifications seconds apart. The receipt already
carries the customer, the items, the total and the confirm button, so the
separate ping is removed and its route deleted.

Where a shop routed the ping somewhere but had no receipt destination at all,
the ping's destination is moved onto the receipt — otherwise that shop would
stop hearing about sales entirely.

Also clears the handoff routes of any shop that had switched those alerts off
with `notify_on_handoff`. That flag no longer gates anything (an empty route is
the switch now), and a value no screen can change must not silently start
sending messages.

Revision ID: e15eef1e9793
Revises: c792a894c872
Create Date: 2026-08-13 12:20:00
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = 'e15eef1e9793'
down_revision: Union[str, Sequence[str], None] = 'c792a894c872'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # A shop with nowhere for the receipt inherits the old ping's destination.
    op.execute(sa.text("""
        UPDATE tenant_settings
        SET notify_routes = jsonb_set(notify_routes, '{receipt}', notify_routes->'order')
        WHERE notify_routes ? 'order'
          AND (NOT notify_routes ? 'receipt' OR notify_routes->'receipt' = '[]'::jsonb)
    """))

    op.execute(sa.text("""
        UPDATE tenant_settings
        SET notify_routes = notify_routes - 'order'
        WHERE notify_routes ? 'order'
    """))

    op.execute(sa.text("""
        UPDATE tenant_settings
        SET notify_routes = notify_routes - 'handoff' - 'customer_waiting'
        WHERE notify_on_handoff = false AND notify_routes IS NOT NULL
    """))


def downgrade() -> None:
    """Put the ping back where the receipt goes — the original destination is
    not recoverable, and no destination at all would be worse."""
    op.execute(sa.text("""
        UPDATE tenant_settings
        SET notify_routes = jsonb_set(notify_routes, '{order}', notify_routes->'receipt')
        WHERE notify_routes ? 'receipt'
    """))
