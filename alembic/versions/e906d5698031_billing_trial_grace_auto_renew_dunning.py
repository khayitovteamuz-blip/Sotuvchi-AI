"""billing: trial, grace, auto-renew, dunning

Adds the three columns the subscription clock needs, then closes the hole they
exist for: every business registered before this migration has no expiry date
at all, which made every expiry check pass. Those accounts are given a trial
that starts now rather than being switched off on the day this deploys.

Revision ID: e906d5698031
Revises: f4a91c73de20
Create Date: 2026-08-13 09:43:13.059401
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e906d5698031'
down_revision: Union[str, Sequence[str], None] = 'f4a91c73de20'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

TRIAL_DAYS = 14


def upgrade() -> None:
    op.add_column('tenants', sa.Column('is_trial', sa.Boolean(), server_default='false', nullable=False))
    op.add_column('tenants', sa.Column('auto_renew', sa.Boolean(), server_default='true', nullable=False))
    op.add_column('tenants', sa.Column('dunning_stage', sa.Integer(), nullable=True))

    # Accounts that never had a period: give them the trial, starting today.
    # Cutting them off instead would switch off working shops on deploy day for
    # a rule that did not exist when they signed up.
    op.execute(
        sa.text(
            "UPDATE tenants "
            "SET subscription_expires_at = now() + make_interval(days => :days), "
            "    is_trial = true "
            "WHERE subscription_expires_at IS NULL"
        ).bindparams(days=TRIAL_DAYS)
    )


def downgrade() -> None:
    op.drop_column('tenants', 'dunning_stage')
    op.drop_column('tenants', 'auto_renew')
    op.drop_column('tenants', 'is_trial')
