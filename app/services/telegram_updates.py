"""Durable, cross-worker idempotency for Telegram webhook delivery."""

from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlalchemy import or_, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import TelegramUpdate

STALE_AFTER = timedelta(minutes=5)


async def claim(session: AsyncSession, tenant_id: str, update_id: Optional[int]) -> bool:
    """Claim an update once; failed or abandoned work may be retried."""
    if update_id is None:
        return True

    now = datetime.now(timezone.utc)
    created = await session.execute(
        insert(TelegramUpdate)
        .values(tenant_id=tenant_id, update_id=update_id, status="processing")
        .on_conflict_do_nothing(index_elements=["tenant_id", "update_id"])
        .returning(TelegramUpdate.update_id)
    )
    if created.scalar_one_or_none() is not None:
        await session.commit()
        return True

    reclaimed = await session.execute(
        update(TelegramUpdate)
        .where(
            TelegramUpdate.tenant_id == tenant_id,
            TelegramUpdate.update_id == update_id,
            or_(
                TelegramUpdate.status == "failed",
                (TelegramUpdate.status == "processing")
                & (TelegramUpdate.received_at < now - STALE_AFTER),
            ),
        )
        .values(
            status="processing",
            received_at=now,
            processed_at=None,
            error=None,
            attempts=TelegramUpdate.attempts + 1,
        )
        .returning(TelegramUpdate.update_id)
    )
    await session.commit()
    return reclaimed.scalar_one_or_none() is not None


async def complete(session: AsyncSession, tenant_id: str, update_id: Optional[int]) -> None:
    if update_id is None:
        return
    await session.execute(
        update(TelegramUpdate)
        .where(
            TelegramUpdate.tenant_id == tenant_id,
            TelegramUpdate.update_id == update_id,
        )
        .values(status="completed", processed_at=datetime.now(timezone.utc), error=None)
    )
    await session.commit()


async def fail(
    session: AsyncSession, tenant_id: str, update_id: Optional[int], error: str
) -> None:
    if update_id is None:
        return
    await session.execute(
        update(TelegramUpdate)
        .where(
            TelegramUpdate.tenant_id == tenant_id,
            TelegramUpdate.update_id == update_id,
        )
        .values(status="failed", error=(error or "unknown")[:1000])
    )
    await session.commit()


async def status(
    session: AsyncSession, tenant_id: str, update_id: int
) -> Optional[str]:
    """Small diagnostic helper used by operations and tests."""
    return await session.scalar(
        select(TelegramUpdate.status).where(
            TelegramUpdate.tenant_id == tenant_id,
            TelegramUpdate.update_id == update_id,
        )
    )
