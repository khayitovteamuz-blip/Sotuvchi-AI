"""
Telegram long-polling — makes the bot work on localhost.

Telegram normally pushes updates to a public webhook URL, which a laptop behind
NAT does not have. getUpdates long-polling reverses the direction: we ask
Telegram for new messages, so no tunnel and no deploy are needed for development.

One poll loop runs per tenant that has a bot token. Production should use
webhooks instead (set PUBLIC_BASE_URL and connect from the Integrations tab).
"""
import asyncio
import json
import logging
from typing import Dict, Optional

import httpx
from sqlalchemy import select

from app.db.base import AsyncSessionLocal
from app.db.models import Tenant
from app.services.bot_service import TELEGRAM_API, bot_service

logger = logging.getLogger("telegram_poller")

POLL_TIMEOUT = 25       # seconds Telegram holds the request open
# Every update type the bot acts on. Missing one here means it never arrives.
ALLOWED_UPDATES = ["message", "callback_query", "my_chat_member"]
ERROR_BACKOFF = 5       # seconds to wait after a failure
REFRESH_INTERVAL = 30   # seconds between tenant-list refreshes


class TelegramPoller:
    """Runs one getUpdates loop per tenant with a configured bot token."""

    def __init__(self) -> None:
        self._tasks: Dict[str, asyncio.Task] = {}   # tenant_id -> polling task
        self._offsets: Dict[str, int] = {}          # tenant_id -> next update_id
        self._supervisor: Optional[asyncio.Task] = None
        self._running = False

    # ─── lifecycle ────────────────────────────────────────────────────────────
    async def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._supervisor = asyncio.create_task(self._supervise())
        logger.info("Telegram polling started (localhost mode)")

    async def stop(self) -> None:
        self._running = False
        if self._supervisor:
            self._supervisor.cancel()
        for task in self._tasks.values():
            task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
        self._tasks.clear()
        logger.info("Telegram polling stopped")

    def status(self) -> dict:
        return {
            "running": self._running,
            "polling_tenants": list(self._tasks.keys()),
        }

    def is_polling(self, tenant_id: str) -> bool:
        task = self._tasks.get(tenant_id)
        return bool(task and not task.done())

    # ─── supervisor: keeps one loop per connected tenant ──────────────────────
    async def _supervise(self) -> None:
        while self._running:
            try:
                async with AsyncSessionLocal() as session:
                    res = await session.execute(
                        select(Tenant).where(
                            Tenant.telegram_bot_token.isnot(None), Tenant.is_active.is_(True)
                        )
                    )
                    tenants = {t.id: t.telegram_bot_token for t in res.scalars().all()}

                # start loops for newly connected bots
                for tenant_id, token in tenants.items():
                    if not self.is_polling(tenant_id):
                        self._tasks[tenant_id] = asyncio.create_task(self._poll_tenant(tenant_id, token))
                        logger.info(f"Polling started for {tenant_id}")

                # stop loops for disconnected bots
                for tenant_id in list(self._tasks):
                    if tenant_id not in tenants:
                        self._tasks.pop(tenant_id).cancel()
                        logger.info(f"Polling stopped for {tenant_id}")

            except asyncio.CancelledError:
                raise
            except Exception as e:
                logger.error(f"Poller supervisor error: {e}")

            await asyncio.sleep(REFRESH_INTERVAL)

    # ─── one tenant's poll loop ───────────────────────────────────────────────
    async def _poll_tenant(self, tenant_id: str, token: str) -> None:
        # getUpdates and webhooks are mutually exclusive
        await bot_service.delete_webhook(token)

        async with httpx.AsyncClient(timeout=POLL_TIMEOUT + 10) as client:
            while self._running:
                try:
                    # Always state the update types explicitly. Telegram remembers
                    # the last allowed_updates it was given, so relying on the
                    # default can silently drop callback_query — which is exactly
                    # how the order confirm button stopped arriving.
                    params = {
                        "timeout": POLL_TIMEOUT,
                        "allowed_updates": json.dumps(ALLOWED_UPDATES),
                    }
                    if tenant_id in self._offsets:
                        params["offset"] = self._offsets[tenant_id]

                    resp = await client.get(f"{TELEGRAM_API.format(token=token)}/getUpdates", params=params)
                    data = resp.json()

                    if not data.get("ok"):
                        logger.error(f"getUpdates failed for {tenant_id}: {data.get('description')}")
                        await asyncio.sleep(ERROR_BACKOFF)
                        continue

                    for update in data.get("result", []):
                        # advance the offset first: a message that crashes the
                        # handler must not be redelivered forever
                        self._offsets[tenant_id] = update["update_id"] + 1
                        await self._handle(tenant_id, update)

                except asyncio.CancelledError:
                    raise
                except (httpx.TimeoutException, httpx.ReadTimeout):
                    continue  # normal for long polling
                except Exception as e:
                    logger.error(f"Polling error for {tenant_id}: {e}")
                    await asyncio.sleep(ERROR_BACKOFF)

    async def _handle(self, tenant_id: str, update: dict) -> None:
        """Process one update with its own DB session."""
        try:
            async with AsyncSessionLocal() as session:
                tenant = await session.get(Tenant, tenant_id)
                if not tenant or not tenant.telegram_bot_token:
                    return
                await bot_service.handle_update(session, tenant, update)
        except Exception as e:
            logger.exception(f"Failed handling update for {tenant_id}: {e}")


telegram_poller = TelegramPoller()
