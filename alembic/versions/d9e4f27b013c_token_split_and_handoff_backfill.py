"""split prompt/output tokens, backfill handoff_reason

Input and output tokens are billed at different rates, so a blended total
cannot be priced. Also backfills handoff_reason for conversations an operator
took over before that field was stamped — without it the escalation rate
under-reports its own history.

Revision ID: d9e4f27b013c
Revises: c5d82e14f6a9
Create Date: 2026-08-11

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d9e4f27b013c"
down_revision: Union[str, None] = "c5d82e14f6a9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "messages",
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "messages",
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
    )

    # Conversations an operator claimed before handoff_reason was recorded. They
    # really were escalations, so leaving them blank would understate the rate.
    op.execute(
        """
        UPDATE conversations
           SET handoff_reason = 'Operator suhbatni qo''lda oldi'
         WHERE handoff_reason IS NULL
           AND (status = 'operator' OR assigned_user_id IS NOT NULL)
        """
    )


def downgrade() -> None:
    op.drop_column("messages", "output_tokens")
    op.drop_column("messages", "prompt_tokens")
