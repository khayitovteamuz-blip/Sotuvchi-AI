"""
Delete message rows older than the retention window.

Why: message history has no cap on its own — the 2026-08-25 project review
flagged this as unbounded growth (message text is the bulk of what a
conversation stores). Conversations and orders are kept forever — they are
the structured record a dispute or support call gets resolved from — only
the raw chat transcript ages out, since it has no value once a conversation
has been closed for a long time.

Run manually:
    .venv/bin/python -m scripts.retention

Daily cron (server vaqti bo'yicha 04:00, backup.sh dan keyin):
    0 4 * * * cd /app && .venv/bin/python -m scripts.retention >> /var/log/sotuvchi-retention.log 2>&1

Env:
    MESSAGE_RETENTION_DAYS   default 365 (app/core/config.py) — <= 0 disables this entirely
    RETENTION_DRY_RUN=1      count what would be deleted without deleting it
"""
import asyncio
import logging
import os
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select

from app.core.config import settings
from app.db.base import AsyncSessionLocal
from app.db.models import Message, TelegramUpdate

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger("retention")


async def main() -> int:
    days = settings.MESSAGE_RETENTION_DAYS
    if days <= 0:
        logger.info("MESSAGE_RETENTION_DAYS <= 0 — retention o'chirilgan, hech narsa qilinmadi.")
        return 0

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    telegram_cutoff = datetime.now(timezone.utc) - timedelta(
        days=max(1, settings.TELEGRAM_UPDATE_RETENTION_DAYS)
    )
    dry_run = os.getenv("RETENTION_DRY_RUN") == "1"

    async with AsyncSessionLocal() as db:
        count = (
            await db.execute(
                select(func.count()).select_from(Message).where(Message.created_at < cutoff)
            )
        ).scalar_one()

        update_count = (
            await db.execute(
                select(func.count())
                .select_from(TelegramUpdate)
                .where(
                    TelegramUpdate.received_at < telegram_cutoff,
                    TelegramUpdate.status.in_(("completed", "failed")),
                )
            )
        ).scalar_one()

        if dry_run:
            logger.info(
                "[DRY RUN] %d ta xabar va %d ta Telegram update yozuvi o'chirilardi.",
                count,
                update_count,
            )
            return 0

        if count:
            await db.execute(delete(Message).where(Message.created_at < cutoff))
        if update_count:
            await db.execute(
                delete(TelegramUpdate).where(
                    TelegramUpdate.received_at < telegram_cutoff,
                    TelegramUpdate.status.in_(("completed", "failed")),
                )
            )
        await db.commit()
        logger.info(
            "%d ta xabar va %d ta Telegram update yozuvi o'chirildi.",
            count,
            update_count,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
