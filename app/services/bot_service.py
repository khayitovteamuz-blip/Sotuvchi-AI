"""
Telegram bot service — tenant-scoped.

Each business connects its OWN bot token (stored on the tenant). Updates arrive
at /api/bot/webhook/{tenant_id}; replies are sent with that tenant's token.
"""
import logging
from typing import Any, Dict, Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import repo
from app.db.models import Tenant
from app.services.ai_agent import ai_agent

logger = logging.getLogger("bot_service")
TELEGRAM_API = "https://api.telegram.org/bot{token}"


class TelegramBotService:
    async def send_message(
        self, token: str, chat_id: str, text: str,
        reply_markup: Optional[Dict[str, Any]] = None, parse_mode: str = "Markdown",
    ) -> bool:
        if not token:
            return False
        payload = {"chat_id": chat_id, "text": text, "parse_mode": parse_mode}
        if reply_markup:
            payload["reply_markup"] = reply_markup
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(f"{TELEGRAM_API.format(token=token)}/sendMessage", json=payload)
                return resp.status_code == 200
        except Exception as e:
            logger.error(f"Telegram sendMessage error: {e}")
            return False

    async def get_me(self, token: str) -> Optional[dict]:
        """Validate a bot token and return bot info (username)."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.get(f"{TELEGRAM_API.format(token=token)}/getMe")
                data = resp.json()
                return data.get("result") if data.get("ok") else None
        except Exception as e:
            logger.error(f"Telegram getMe error: {e}")
            return None

    async def set_webhook(self, token: str, url: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{TELEGRAM_API.format(token=token)}/setWebhook",
                    json={"url": url, "allowed_updates": ["message", "callback_query"]},
                )
                return resp.json().get("ok", False)
        except Exception as e:
            logger.error(f"Telegram setWebhook error: {e}")
            return False

    async def delete_webhook(self, token: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(f"{TELEGRAM_API.format(token=token)}/deleteWebhook")
                return resp.json().get("ok", False)
        except Exception:
            return False

    # ── incoming update ──
    async def handle_update(self, session: AsyncSession, tenant: Tenant, update: Dict[str, Any]):
        token = tenant.telegram_bot_token
        if "message" in update:
            await self._handle_message(session, tenant, token, update["message"])
        elif "callback_query" in update:
            await self._handle_callback(session, tenant, token, update["callback_query"])

    async def _handle_message(self, session, tenant, token, msg):
        chat_id = str(msg["chat"]["id"])
        user_name = msg.get("from", {}).get("first_name", "Mijoz")
        text = msg.get("text", "")

        # Operator pairing: "/operator ABC123" registers this chat for alerts.
        # Handled before any conversation is created — the owner is not a lead.
        if text.startswith("/operator"):
            from app.services import notify_service
            cfg = await repo.get_settings(session, tenant.id)
            parts = text.split(maxsplit=1)
            code = parts[1] if len(parts) > 1 else ""
            reply = await notify_service.try_pair_operator(
                session, tenant, cfg, chat_id, code, user_name
            )
            if reply:
                await self.send_message(token, chat_id, reply)
            else:
                await self.send_message(
                    token, chat_id,
                    "❌ Kod noto'g'ri yoki eskirgan.\nPaneldagi *Integratsiyalar* bo'limidan yangi kod oling."
                )
            return

        # An operator's own chat is not a customer conversation
        cfg = await repo.get_settings(session, tenant.id)
        if cfg.operator_chat_id and chat_id == cfg.operator_chat_id and text.startswith("/"):
            await self.send_message(
                token, chat_id,
                "ℹ️ Bu chat operator bildirishnomalari uchun ulangan.\n"
                "Mijozlarga javob berish uchun paneldagi *Inbox* bo'limidan foydalaning."
            )
            return

        conv = await repo.get_or_create_conversation(
            session, tenant.id, "telegram", chat_id, customer_name=user_name
        )

        if text == "/start":
            greeting = cfg.greeting_message or (
                f"Assalomu alaykum, {user_name}! 👋\nMen {cfg.ai_name or 'Sotuvchi AI'} — "
                f"savdo bo'yicha yordamchingizman. Nima qidiryapsiz?"
            )
            keyboard = {"inline_keyboard": [
                [{"text": "🛍 Katalog", "callback_data": "btn_catalog"},
                 {"text": "📞 Operator", "callback_data": "btn_operator"}],
            ]}
            await self.send_message(token, chat_id, greeting, reply_markup=keyboard)
            return

        # A human owns this conversation (or the bot is off): record the message
        # and ping the operator, otherwise the customer waits on a silent chat.
        if conv.status == "operator" or not cfg.bot_enabled:
            await repo.add_message(session, tenant.id, conv, "user", text)
            from app.services import notify_service
            await notify_service.notify_customer_waiting(session, tenant, cfg, conv, text)
            return

        resp = await ai_agent.generate_response(session, tenant, conv, text, user_name)
        await self.send_message(token, chat_id, resp.reply_text)

    async def _handle_callback(self, session, tenant, token, query):
        chat_id = str(query["message"]["chat"]["id"])
        data = query.get("data", "")
        user_name = query.get("from", {}).get("first_name", "Mijoz")
        conv = await repo.get_or_create_conversation(
            session, tenant.id, "telegram", chat_id, customer_name=user_name
        )

        if data == "btn_catalog":
            products = await repo.list_products(session, tenant.id)
            if not products:
                await self.send_message(token, chat_id, "Katalog hozircha bo'sh.")
                return
            reply = "🛍 **Katalog:**\n\n"
            for p in products[:15]:
                reply += f"• **{p.name}** — {p.price:,.0f} {p.currency}\n"
            reply += "\nXarid uchun mahsulot nomini yozing!"
            await self.send_message(token, chat_id, reply)

        elif data == "btn_operator":
            conv.status = "operator"
            conv.handoff_reason = "Mijoz operator tugmasini bosdi"
            await session.commit()

            from app.services import notify_service
            cfg = await repo.get_settings(session, tenant.id)
            notified = await notify_service.notify_handoff(
                session, tenant, cfg, conv, conv.handoff_reason
            )
            await self.send_message(
                token, chat_id,
                "👨‍💼 Operatorga xabar berdim! Tez orada javob berishadi."
                if notified else
                "👨‍💼 So'rovingiz qabul qilindi. Operatorimiz tez orada bog'lanadi."
            )


bot_service = TelegramBotService()
