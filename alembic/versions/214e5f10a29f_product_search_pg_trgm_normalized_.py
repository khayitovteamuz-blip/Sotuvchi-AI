"""product search: pg_trgm, normalized search_text, GIN index

Revision ID: 214e5f10a29f
Revises: 6ca7c8866445
Create Date: 2026-08-08 19:03:34.876698

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '214e5f10a29f'
down_revision: Union[str, Sequence[str], None] = '6ca7c8866445'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Trigram search for the catalog.

    Uzbek has no Postgres stemmer and is agglutinative ("noutbuk" / "noutbuklar"
    / "noutbukni"), and customers type with mixed scripts and typos ("ayfon").
    Trigram matching handles all three; full-text search would not.
    """
    op.execute("CREATE EXTENSION IF NOT EXISTS pg_trgm")

    # Normalisation shared by the stored column and the ranking expression.
    # Strips the apostrophe variants Uzbek users type inconsistently
    # (o'zbek / oʻzbek / oʼzbek) so they all match.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION sotuvchi_norm(t text) RETURNS text
        LANGUAGE sql IMMUTABLE STRICT PARALLEL SAFE AS $fn$
            SELECT lower(translate(coalesce(t, ''), E'ʻʼ‘’`´''"', ''))
        $fn$
        """
    )

    # GENERATED column: Postgres recomputes it on every INSERT/UPDATE, so a
    # product added or edited in the admin panel is searchable immediately with
    # no reindex step and no way for the app to forget.
    op.execute(
        """
        ALTER TABLE products
        ADD COLUMN search_text text
        GENERATED ALWAYS AS (
            sotuvchi_norm(coalesce(name,'') || ' ' || coalesce(category,'') || ' ' || coalesce(description,''))
        ) STORED
        """
    )

    # GIN trigram indexes serve both ILIKE '%...%' and the % similarity operator
    op.execute("CREATE INDEX ix_products_search_trgm ON products USING gin (search_text gin_trgm_ops)")
    op.execute("CREATE INDEX ix_products_name_trgm ON products USING gin (sotuvchi_norm(name) gin_trgm_ops)")
    # Supports the common "cheapest in this category, in stock" browse path
    op.execute("CREATE INDEX ix_products_tenant_cat_price ON products (tenant_id, category, price)")


def downgrade() -> None:
    """Downgrade schema."""
    op.execute("DROP INDEX IF EXISTS ix_products_tenant_cat_price")
    op.execute("DROP INDEX IF EXISTS ix_products_name_trgm")
    op.execute("DROP INDEX IF EXISTS ix_products_search_trgm")
    op.execute("ALTER TABLE products DROP COLUMN IF EXISTS search_text")
    op.execute("DROP FUNCTION IF EXISTS sotuvchi_norm(text)")
