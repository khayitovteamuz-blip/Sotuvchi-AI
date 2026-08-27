"""off topic streak

Ikkinchi ketma-ket mavzudan tashqari xabardan keyin AI jim turadi — bloklamaydi,
faqat jim turadi, mijoz mavzuga qaytishi bilan darhol tiklanadi.

Buni ishonchli aniqlash uchun (matn har safar boshqacha chiqadi, mos
kelishini tekshirish mo'rt bo'lardi) model endi decline_off_topic degan
bo'sh funksiyani chaqiradi — xuddi handoff_to_human kabi, bu ham "bu holat
yuz berdi" degan aniq signal, matn emas.

Revision ID: a5d4f372838f
Revises: a96c7a980e29
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a5d4f372838f"
down_revision: Union[str, Sequence[str], None] = "a96c7a980e29"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ADDENDUM = """

17a. MAVZUDAN CHIQISH JAVOBIDAN OLDIN — decline_off_topic FUNKSIYASINI CHAQIRING.
   17-qoidaga ko'ra rad javobi berishdan OLDIN har doim decline_off_topic
   funksiyasini chaqiring (argumentlarsiz). Bu funksiya hech narsani
   o'zgartirmaydi — faqat tizimga "bu savol mavzudan tashqari edi" deb
   bildiradi. Chaqirmasangiz, tizim buni bilmaydi. Do'kon mavzusidagi oddiy
   javobda bu funksiyani chaqirmang."""


def upgrade() -> None:
    op.add_column(
        "conversations",
        sa.Column("off_topic_streak", sa.Integer(), nullable=False, server_default="0"),
    )
    op.execute(
        sa.text(
            "UPDATE platform_ai_settings SET guardrails_text = guardrails_text || :addendum "
            "WHERE id = 'global'"
        ).bindparams(addendum=_ADDENDUM)
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE platform_ai_settings SET guardrails_text = replace(guardrails_text, :addendum, '') "
            "WHERE id = 'global'"
        ).bindparams(addendum=_ADDENDUM)
    )
    op.drop_column("conversations", "off_topic_streak")
