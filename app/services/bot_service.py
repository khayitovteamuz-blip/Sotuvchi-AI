"""
Telegram bot service — tenant-scoped.

Each business connects its OWN bot token (stored on the tenant). Updates arrive
at /api/bot/webhook/{tenant_id}; replies are sent with that tenant's token.

The AI answers customers over two paths, and the same conversation logic
serves both (_process_customer_message):

  • the bot's own chat — an ordinary `message` update, reply sent as the bot.
    This always works and needs nothing but a token.
  • the owner's personal account — the owner connects this bot from their
    Telegram app (Settings → Chat Automation, or Settings → Telegram Business
    → Chatbots on older versions), customer messages then arrive as
    `business_message`, and a reply carrying that business_connection_id shows
    up as coming from the owner's own account rather than a bot.

The connection therefore upgrades WHO the reply appears to come from; it is
not what turns the AI on. A shop that has not connected a personal account
still sells — it just sells as a bot.
"""
import asyncio
import json
import logging
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import repo
from app.db.models import Tenant
from app.services.ai_agent import (ai_agent, contact_fallback_text,
                                   contact_reminder_due)
from app.services.storage_service import local_path as _local_photo

logger = logging.getLogger("bot_service")
TELEGRAM_API = "https://api.telegram.org/bot{token}"

# Inline media must fit in the model request; Telegram voice/photos are far
# smaller than this in practice, so the cap only guards against odd uploads.
MAX_MEDIA_BYTES = 15 * 1024 * 1024

# Telegram clears "typing…" after about five seconds, so it has to be resent
# while a slow turn is still being generated.
TYPING_REFRESH_SECONDS = 4.0


def _is_markup_error(data: dict) -> bool:
    """Did Telegram reject the text because of its Markdown, not its content?"""
    desc = str(data.get("description", "")).lower()
    return "parse" in desc and "entit" in desc


# `/ulash` is the command now. The two older ones stay: an owner may be reading
# instructions written before this change, and a command that quietly stops
# working looks like a broken bot.
PAIR_COMMANDS = ("/ulash", "/operator", "/guruh")


def _not_a_receipt_text(lang: Optional[str], name: str) -> str:
    """Fixed wording for "that image is not a payment slip".

    Deterministic on purpose: this message protects a payment, so it must say
    the same thing every time regardless of what the model would rather sell.
    """
    if (lang or "uz") == "ru":
        return (f"{name}, спасибо! 🙏 Но это фото не похоже на чек об оплате.\n\n"
                "Пришлите, пожалуйста, чёткий скриншот чека из банковского приложения — "
                "чтобы были видны сумма и дата.\n\n"
                "Ваш заказ не отменён, он ждёт оплату.")
    if lang == "en":
        return (f"{name}, thank you! 🙏 That photo does not look like a payment receipt.\n\n"
                "Please send a clear screenshot of the receipt from your banking app, "
                "with the amount and date visible.\n\n"
                "Your order is still open and waiting for payment.")
    return (f"{name}, rahmat! 🙏 Lekin bu rasm to'lov chekiga o'xshamadi.\n\n"
            "Iltimos, bank ilovangizdan chekning aniq rasmini yuboring — "
            "summa va sana ko'rinib tursin.\n\n"
            "Buyurtmangiz bekor qilinmadi, to'lov kutilmoqda.")


def _media_kind_label(msg: dict) -> str:
    """What kind of thing the customer sent, from the message alone.

    Deliberately independent of downloading the file: the label must still
    appear when the download fails, or the Inbox shows an empty bubble.
    """
    if msg.get("voice") or msg.get("audio"):
        return "🎤 [ovozli xabar]"
    if msg.get("photo"):
        return "📷 [rasm yubordi]"
    if msg.get("video") or msg.get("video_note"):
        return "🎥 [video xabar]"
    if msg.get("document"):
        return "📎 [fayl yubordi]"
    return ""


def _is_pair_command(text: str) -> bool:
    return bool(text) and text.split(" ", 1)[0].split("@")[0] in PAIR_COMMANDS


class TelegramBotService:
    async def _post_message(
        self, token: str, chat_id: str, text: str,
        reply_markup: Optional[Dict[str, Any]], parse_mode: Optional[str], timeout: float,
        business_connection_id: Optional[str] = None,
    ) -> Optional[dict]:
        """Send one message, and if Markdown is what broke it, send it plain.

        The reply text is written by a model and product names come from the
        shop's own catalogue, so a stray '*' or '_' is ordinary. Telegram
        answers 400 to an unbalanced entity, and the customer used to be left
        with silence — a lost sale over a punctuation mark. Losing the bold is
        the cheaper failure.
        """
        payload: Dict[str, Any] = {"chat_id": chat_id, "text": text}
        if parse_mode:
            payload["parse_mode"] = parse_mode
        if reply_markup:
            payload["reply_markup"] = reply_markup
        if business_connection_id:
            # Sent on behalf of the owner's own account instead of the bot —
            # this is the entire point of the Business integration.
            payload["business_connection_id"] = business_connection_id

        url = f"{TELEGRAM_API.format(token=token)}/sendMessage"
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                resp = await client.post(url, json=payload)
                data = resp.json()
                if data.get("ok"):
                    return data["result"]

                if parse_mode and _is_markup_error(data):
                    logger.info("Telegram rejected the Markdown — resending as plain text")
                    payload.pop("parse_mode")
                    resp = await client.post(url, json=payload)
                    data = resp.json()
                    if data.get("ok"):
                        return data["result"]

                logger.warning(f"sendMessage failed: {str(data)[:180]}")
                return None
        except Exception as e:
            logger.error(f"Telegram sendMessage error: {e}")
            return None

    async def send_message(
        self, token: str, chat_id: str, text: str,
        reply_markup: Optional[Dict[str, Any]] = None, parse_mode: str = "Markdown",
        business_connection_id: Optional[str] = None,
    ) -> bool:
        if not token:
            return False
        return await self._post_message(
            token, chat_id, text, reply_markup, parse_mode, 10.0, business_connection_id
        ) is not None

    async def send_message_full(
        self, token: str, chat_id: str, text: str,
        reply_markup: Optional[Dict[str, Any]] = None, parse_mode: str = "Markdown",
        business_connection_id: Optional[str] = None,
    ) -> Optional[dict]:
        """Like send_message but returns the sent message — we need its id to
        edit the receipt once someone confirms."""
        if not token:
            return None
        return await self._post_message(
            token, chat_id, text, reply_markup, parse_mode, 15.0, business_connection_id
        )

    async def edit_message(
        self, token: str, chat_id: str, message_id: str, text: str,
        reply_markup: Optional[Dict[str, Any]] = None, parse_mode: str = "Markdown",
        business_connection_id: Optional[str] = None,
    ) -> bool:
        payload = {"chat_id": chat_id, "message_id": int(message_id),
                   "text": text, "parse_mode": parse_mode}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        if business_connection_id:
            payload["business_connection_id"] = business_connection_id
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(f"{TELEGRAM_API.format(token=token)}/editMessageText", json=payload)
                return resp.json().get("ok", False)
        except Exception as e:
            logger.error(f"Telegram editMessageText error: {e}")
            return False

    async def edit_caption(
        self, token: str, chat_id: str, message_id: str, caption: str,
        reply_markup: Optional[Dict[str, Any]] = None,
        business_connection_id: Optional[str] = None,
    ) -> bool:
        """A photo message carries a caption, not text — editMessageText fails on it."""
        payload = {"chat_id": chat_id, "message_id": int(message_id),
                   "caption": caption[:1024], "parse_mode": "Markdown"}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
        if business_connection_id:
            payload["business_connection_id"] = business_connection_id
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(f"{TELEGRAM_API.format(token=token)}/editMessageCaption", json=payload)
                return resp.json().get("ok", False)
        except Exception as e:
            logger.error(f"Telegram editMessageCaption error: {e}")
            return False

    async def answer_callback(
        self, token: str, callback_id: str, text: str = "", alert: bool = False
    ) -> bool:
        """Acknowledge a button tap — without this the client spinner hangs."""
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{TELEGRAM_API.format(token=token)}/answerCallbackQuery",
                    json={"callback_query_id": callback_id, "text": text[:200], "show_alert": alert},
                )
                return resp.json().get("ok", False)
        except Exception as e:
            logger.error(f"Telegram answerCallbackQuery error: {e}")
            return False

    async def send_chat_action(
        self, token: str, chat_id: str, action: str = "typing",
        business_connection_id: Optional[str] = None,
    ) -> bool:
        """Show "typing…" in the customer's chat."""
        payload: Dict[str, Any] = {"chat_id": chat_id, "action": action}
        if business_connection_id:
            payload["business_connection_id"] = business_connection_id
        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{TELEGRAM_API.format(token=token)}/sendChatAction", json=payload
                )
                return resp.json().get("ok", False)
        except Exception as e:
            logger.info(f"sendChatAction skipped: {e}")
            return False

    @asynccontextmanager
    async def typing(self, token: str, chat_id: str, business_connection_id: Optional[str] = None):
        """Keep "typing…" alive for as long as the block runs.

        A turn can take a minute when the model is busy, and a chat that shows
        nothing at all reads as a dead bot — customers gave up and left before
        the answer arrived. The indicator expires after ~5s, so it is refreshed
        until the reply is ready.

        Every failure here is swallowed on purpose: this is decoration, and it
        must never be the reason a customer does not get their answer.
        """
        async def refresh():
            while True:
                await self.send_chat_action(token, chat_id, "typing", business_connection_id)
                await asyncio.sleep(TYPING_REFRESH_SECONDS)

        task = asyncio.create_task(refresh())
        try:
            yield
        finally:
            task.cancel()
            # Let the cancellation settle so a half-sent request cannot outlive
            # the turn and stamp "typing…" onto an already-answered chat.
            await asyncio.gather(task, return_exceptions=True)

    async def send_location(self, token: str, chat_id: str, lat: float, lon: float) -> bool:
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.post(
                    f"{TELEGRAM_API.format(token=token)}/sendLocation",
                    json={"chat_id": chat_id, "latitude": lat, "longitude": lon},
                )
                return resp.json().get("ok", False)
        except Exception as e:
            logger.error(f"Telegram sendLocation error: {e}")
            return False

    async def send_photo(
        self, token: str, chat_id: str, photo_url: str, caption: Optional[str] = None,
        business_connection_id: Optional[str] = None,
    ) -> bool:
        """Send a product image, by URL or from our own disk."""
        return await self.send_photo_full(
            token, chat_id, photo_url, caption, business_connection_id=business_connection_id
        ) is not None

    async def send_photo_full(
        self, token: str, chat_id: str, photo: str,
        caption: Optional[str] = None, reply_markup: Optional[Dict[str, Any]] = None,
        business_connection_id: Optional[str] = None,
    ) -> Optional[dict]:
        """Send a photo and return the sent message.

        `photo` is one of three things: an http(s) URL Telegram fetches itself,
        a Telegram file_id it already holds, or a path under /static/uploads —
        a picture the shop owner uploaded through the panel. The last case is
        the common one and it cannot be fetched by URL (localhost, or a host
        with no public name), so those bytes are uploaded with the request.
        """
        if not token or not photo:
            return None
        payload: Dict[str, Any] = {"chat_id": chat_id}
        if caption:
            payload["caption"] = caption[:1024]
            payload["parse_mode"] = "Markdown"
        if business_connection_id:
            payload["business_connection_id"] = business_connection_id

        local = _local_photo(photo)
        files = None
        if local is None:
            payload["photo"] = photo
        else:
            files = {"photo": (local.name, local.read_bytes())}
        if reply_markup:
            # `files` posts as multipart form data, where reply_markup must be a
            # JSON string; `json=` posts a real JSON body, where it must not be.
            payload["reply_markup"] = json.dumps(reply_markup) if files else reply_markup

        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                url = f"{TELEGRAM_API.format(token=token)}/sendPhoto"
                resp = (await client.post(url, data=payload, files=files) if files
                        else await client.post(url, json=payload))
                data = resp.json()
                if not data.get("ok"):
                    logger.warning(f"sendPhoto failed: {str(data)[:180]}")
                    return None
                return data["result"]
        except Exception as e:
            logger.error(f"Telegram sendPhoto error: {e}")
            return None

    async def send_voice_full(
        self, token: str, chat_id: str, file_id: str, caption: Optional[str] = None,
        business_connection_id: Optional[str] = None,
    ) -> Optional[dict]:
        """Pass a voice note through by file_id; returns the sent message.

        The id matters: a staff member replying to this voice note in the
        group is answering the customer who recorded it.
        """
        payload: Dict[str, Any] = {"chat_id": chat_id, "voice": file_id}
        if caption:
            payload["caption"] = caption[:1024]
        if business_connection_id:
            payload["business_connection_id"] = business_connection_id
        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                resp = await client.post(
                    f"{TELEGRAM_API.format(token=token)}/sendVoice", json=payload
                )
                data = resp.json()
                if not data.get("ok"):
                    logger.warning(f"sendVoice failed: {str(data)[:180]}")
                    return None
                return data["result"]
        except Exception as e:
            logger.error(f"Telegram sendVoice error: {e}")
            return None

    async def send_voice(
        self, token: str, chat_id: str, file_id: str, caption: Optional[str] = None,
        business_connection_id: Optional[str] = None,
    ) -> bool:
        return await self.send_voice_full(
            token, chat_id, file_id, caption, business_connection_id
        ) is not None

    async def send_document(
        self, token: str, chat_id: str, file_id: str, caption: Optional[str] = None,
        business_connection_id: Optional[str] = None,
    ) -> bool:
        """Pass a file straight through by the id Telegram already holds."""
        payload: Dict[str, Any] = {"chat_id": chat_id, "document": file_id}
        if caption:
            payload["caption"] = caption[:1024]
        if business_connection_id:
            payload["business_connection_id"] = business_connection_id
        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                resp = await client.post(
                    f"{TELEGRAM_API.format(token=token)}/sendDocument", json=payload
                )
                data = resp.json()
                if not data.get("ok"):
                    logger.warning(f"sendDocument failed: {str(data)[:180]}")
                return bool(data.get("ok"))
        except Exception as e:
            logger.error(f"Telegram sendDocument error: {e}")
            return False

    async def send_media_group(
        self, token: str, chat_id: str, items: list,
        business_connection_id: Optional[str] = None,
    ) -> bool:
        """Send 2-10 product images as one album.

        Locally stored pictures ride along as multipart parts referenced by
        `attach://`, which is how Telegram accepts uploads inside an album.
        """
        if not token or len(items) < 2:
            return False

        media, files = [], {}
        for i, it in enumerate(items[:10]):
            local = _local_photo(it["url"])
            if local is None:
                source = it["url"]
            else:
                part = f"photo{i}"
                files[part] = (local.name, local.read_bytes())
                source = f"attach://{part}"
            entry = {"type": "photo", "media": source}
            if i == 0 and it.get("caption"):
                entry["caption"] = it["caption"][:1024]
                entry["parse_mode"] = "Markdown"
            media.append(entry)

        base: Dict[str, Any] = {"chat_id": chat_id, "media": media}
        if business_connection_id:
            base["business_connection_id"] = business_connection_id

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                url = f"{TELEGRAM_API.format(token=token)}/sendMediaGroup"
                if files:
                    form = dict(base)
                    form["media"] = json.dumps(media)
                    resp = await client.post(url, data=form, files=files)
                else:
                    resp = await client.post(url, json=base)
                if resp.status_code != 200:
                    logger.warning(f"sendMediaGroup failed: {resp.text[:180]}")
                return resp.status_code == 200
        except Exception as e:
            logger.error(f"Telegram sendMediaGroup error: {e}")
            return False

    async def download_file(self, token: str, file_id: str) -> Optional[bytes]:
        """Fetch a photo/voice the customer sent, so the model can look at it."""
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                info = await client.get(
                    f"{TELEGRAM_API.format(token=token)}/getFile", params={"file_id": file_id}
                )
                data = info.json()
                if not data.get("ok"):
                    logger.warning(f"getFile failed: {data.get('description')}")
                    return None
                path = data["result"]["file_path"]
                if data["result"].get("file_size", 0) > MAX_MEDIA_BYTES:
                    logger.warning("Media too large, skipping")
                    return None
                dl = await client.get(f"https://api.telegram.org/file/bot{token}/{path}")
                return dl.content if dl.status_code == 200 else None
        except Exception as e:
            logger.error(f"Telegram download error: {e}")
            return None

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

    async def set_webhook(self, token: str, url: str, secret: Optional[str] = None) -> bool:
        try:
            payload = {
                "url": url,
                "allowed_updates": [
                    "message", "channel_post", "callback_query", "my_chat_member",
                    "business_connection", "business_message",
                    "edited_business_message", "deleted_business_messages",
                ],
            }
            if secret:
                # Telegram sends this back on every update as the
                # X-Telegram-Bot-Api-Secret-Token header. The tenant id in the
                # webhook URL is public and proves nothing, so this shared secret
                # is what separates a real update from a forged one.
                payload["secret_token"] = secret
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(
                    f"{TELEGRAM_API.format(token=token)}/setWebhook", json=payload
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
        if "business_connection" in update:
            await self._handle_business_connection(session, tenant, update["business_connection"])
        elif "business_message" in update:
            await self._handle_business_message(
                session, tenant, token, update["business_message"], update.get("update_id")
            )
        elif "edited_business_message" in update or "deleted_business_messages" in update:
            # An edit or delete in the customer's chat — the AI already replied
            # to the original text; there is nothing useful to do with either.
            pass
        elif "message" in update:
            await self._handle_message(
                session, tenant, token, update["message"], update.get("update_id")
            )
        elif "channel_post" in update:
            # A channel is a one-way destination: the only thing worth reading
            # from one is the pairing command an admin posts there.
            await self._handle_channel_post(session, tenant, token, update["channel_post"])
        elif "callback_query" in update:
            await self._handle_callback(session, tenant, token, update["callback_query"])

    async def _handle_business_connection(self, session, tenant: Tenant, conn: Dict[str, Any]):
        """The owner just connected (or reconfigured) this bot as their Business chatbot."""
        tenant.telegram_business_connection_id = conn.get("id")
        owner = conn.get("user") or {}
        tenant.telegram_business_owner_id = str(owner["id"]) if owner.get("id") is not None else None
        tenant.telegram_business_enabled = bool(conn.get("is_enabled"))
        await session.commit()
        logger.info(
            "Telegram Business ulanish: tenant=%s enabled=%s",
            tenant.id, tenant.telegram_business_enabled,
        )

    async def _handle_business_message(self, session, tenant: Tenant, token, msg, source_update_id=None):
        """A message in a chat the owner's connected personal account is part of.

        This fires for BOTH sides of the conversation — the customer's messages
        and any the owner types themselves from their own phone. Only the
        customer's should ever reach the AI; replying to the owner's own words
        would have it talk to itself.
        """
        if not tenant.telegram_business_enabled or not tenant.telegram_business_connection_id:
            return
        if msg.get("chat", {}).get("type") != "private":
            return  # AI faqat mijoz bilan shaxsiy suhbatda javob beradi

        chat_id = str(msg["chat"]["id"])
        sender_id = str((msg.get("from") or {}).get("id") or "")
        if tenant.telegram_business_owner_id and sender_id == tenant.telegram_business_owner_id:
            # Egasi mijozga o'zi (telefonidan) javob berdi. AI aralashmaydi,
            # lekin bu javob yozib olinadi: aks holda Inboxda suhbat javobsiz
            # ko'rinadi va "operator jim" soati yurishda davom etib, eslatma
            # ega ishlayotgan suhbatga bostirib kirardi.
            await self._record_owner_reply(session, tenant, chat_id, msg)
            return

        bc_id = msg.get("business_connection_id") or tenant.telegram_business_connection_id
        user_name = msg.get("from", {}).get("first_name", "Mijoz")
        text = msg.get("text") or msg.get("caption") or ""

        await self._process_customer_message(
            session, tenant, token, msg, chat_id, user_name, text,
            source_update_id=source_update_id, business_connection_id=bc_id,
        )

    async def _handle_channel_post(self, session, tenant, token, post):
        """A channel is a destination, not a conversation.

        The only thing worth reading from one is the pairing command an admin
        posts there; everything else is the bot's own output echoing back.
        """
        text = post.get("text") or post.get("caption") or ""
        if not _is_pair_command(text):
            return
        chat_id = str(post["chat"]["id"])
        title = post["chat"].get("title", "Kanal")
        reply = await self._try_pair(session, tenant, chat_id, "channel", title, text)
        if reply:
            await self.send_message(token, chat_id, reply)

    async def _try_pair(self, session, tenant, chat_id, kind, title, text):
        """Shared by private chats, groups and channels — one command, one path."""
        from app.services import routing_service
        cfg = await repo.get_settings(session, tenant.id)
        parts = text.split()
        code = parts[-1] if len(parts) > 1 else ""
        return await routing_service.try_pair(
            session, tenant, cfg, chat_id, kind, title, code
        )

    async def _handle_message(self, session, tenant, token, msg, source_update_id=None):
        """A message sent straight to the bot's own chat.

        The AI answers here too, as the bot itself. Connecting a personal
        account (Telegram Business) upgrades WHO the reply comes from, it is
        not what switches the AI on — a shop that has not connected one, or
        cannot, must still have a working salesperson rather than silence.
        """
        chat_id = str(msg["chat"]["id"])
        user_name = msg.get("from", {}).get("first_name", "Mijoz")
        # A photo's text arrives as "caption", not "text"
        text = msg.get("text") or msg.get("caption") or ""

        # Group chats are team channels, never customer conversations
        if msg["chat"].get("type") in ("group", "supergroup"):
            await self._handle_group_message(session, tenant, token, msg, chat_id, text)
            return

        # Pairing: "/ulash ABC123" registers this chat as a notification
        # destination. Handled before any conversation is created — the owner is
        # not a lead. `/operator` still works: an owner may have the old
        # instructions open, and a command that silently stops working reads as
        # a broken product.
        if _is_pair_command(text):
            reply = await self._try_pair(session, tenant, chat_id, "private", user_name, text)
            await self.send_message(
                token, chat_id,
                reply or "❌ Kod noto'g'ri yoki eskirgan.\n"
                         "Panelda *Sozlamalar → Boshqa ulanishlar → Integratsiyalar* bo'limidan yangi kod oling."
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

        # Same conversation logic as the business path; no connection id, so
        # the reply goes out as the bot. A message here and one to a connected
        # personal account are different chats, so nothing is answered twice.
        await self._process_customer_message(
            session, tenant, token, msg, chat_id, user_name, text,
            source_update_id=source_update_id, business_connection_id=None,
        )

    async def _record_owner_reply(self, session, tenant, chat_id: str, msg: dict) -> None:
        """Store what the owner typed to the customer from their own phone.

        Two things depend on it: the Inbox shows the full conversation rather
        than only the AI's half, and the "nobody answered" clock restarts —
        a shop that is answering by hand must never be interrupted by our
        "call us instead" message.
        """
        text = msg.get("text") or msg.get("caption") or ""
        conv = await repo.get_or_create_conversation(
            session, tenant.id, "telegram", chat_id,
            customer_name=msg.get("chat", {}).get("first_name") or "Mijoz",
        )
        await repo.add_message(session, tenant.id, conv, "operator", text or "[media]")
        # Yangi jimlik boshlansa, raqam qaytadan berilishi mumkin bo'lsin.
        await repo.release_contact_reminder(session, tenant.id, conv.id)

    async def _process_customer_message(
        self, session, tenant, token, msg, chat_id, user_name, text,
        source_update_id=None, business_connection_id=None,
    ):
        """The AI sales conversation — reached only via Telegram Business now.

        Everything here used to run straight off the bot's own chat; it moved
        wholesale onto the business_message path so a reply always carries
        business_connection_id and arrives as the owner's own account.
        """
        cfg = await repo.get_settings(session, tenant.id)

        # Flood guard: one chat sending messages faster than a person can type
        # is either a script or a bug on the customer's side, and every one of
        # these messages would otherwise reach the AI call further down.
        # Silently dropped, not replied to — replying "siz juda tez yozyapsiz"
        # to a flood just gives it something to react to.
        from app.core import rate_limit
        if not rate_limit.allow(f"chat:{tenant.id}:{chat_id}", max_calls=12, window_seconds=10):
            logger.warning("Xabar chastotasi chegarasi: tenant=%s chat=%s", tenant.id, chat_id)
            return

        conv = await repo.get_or_create_conversation(
            session, tenant.id, "telegram", chat_id, customer_name=user_name
        )
        if business_connection_id and conv.telegram_business_connection_id != business_connection_id:
            conv.telegram_business_connection_id = business_connection_id
        # Keep the Telegram handle: the team needs a way back to the customer
        # when a phone number is wrong or unreachable.
        uname = msg.get("from", {}).get("username")
        if uname and conv.customer_username != uname:
            conv.customer_username = uname
        await session.commit()

        # Bloklangan suhbat — hech qanday javob yo'q, hatto /start ga ham.
        # Jim turish ataylab: har xabarga "siz bloklangansiz" deb javob berish
        # haqoratlayotgan odamga o'yin beradi va u davom etaveradi.
        if conv.blocked_at:
            logger.info("Bloklangan suhbatdan xabar: tenant=%s conv=%s", tenant.id, conv.id)
            return

        if text == "/start":
            greeting = cfg.greeting_message or (
                f"Assalomu alaykum, {user_name}! 👋\nMen {cfg.ai_name or 'Sotuvchi AI'} — "
                f"savdo bo'yicha yordamchingizman. Nima qidiryapsiz?"
            )
            # "Operator" tugmasi ataylab yo'q: salomlashuvdayoq odam so'rash
            # taklif qilinsa, mijoz AI bilan gaplashib ham ko'rmaydi. Kerak
            # bo'lsa u so'z bilan so'raydi va AI uzatadi.
            keyboard = {"inline_keyboard": [
                [{"text": "🛍 Katalog", "callback_data": "btn_catalog"}],
            ]}
            await self.send_message(
                token, chat_id, greeting, reply_markup=keyboard,
                business_connection_id=business_connection_id,
            )
            return

        # A pinned location is the delivery address — keep it on the conversation
        # so create_order can attach it whenever the customer gets that far.
        if msg.get("location"):
            loc = msg["location"]
            conv.last_latitude = loc.get("latitude")
            conv.last_longitude = loc.get("longitude")
            await session.commit()
            text = text or "📍 [lokatsiya yubordi]"

        # Keep the photo's file_id: a payment slip must reach the team as an
        # image, and Telegram lets us forward it by id without re-uploading.
        if msg.get("photo"):
            file_id = msg["photo"][-1]["file_id"]
            conv.last_photo_file_id = file_id
            await session.commit()
            # If a payment is pending for this chat, the slip goes to the team now
            from app.services import group_service
            slip = await group_service.attach_payment_slip(session, tenant, conv.id, file_id)
            # Not a receipt: the team never sees it, and the customer is told
            # directly. This reply is fixed text, not model output — the same
            # instruction handed to the model was ignored twice in testing, and
            # it kept pitching products at someone who owes money. A message
            # that guards a payment cannot depend on the model's mood.
            if slip.get("not_receipt"):
                await self.send_message(
                    token, chat_id, _not_a_receipt_text(cfg.ai_language, user_name),
                    business_connection_id=business_connection_id,
                )
                await repo.add_message(session, tenant.id, conv, "user", text or "📷 [rasm yubordi]")
                await repo.add_message(
                    session, tenant.id, conv, "assistant",
                    _not_a_receipt_text(cfg.ai_language, user_name),
                )
                return

        # Photo / voice: customers here often show a product or just talk.
        # Gemini reads both, so hand the bytes straight to the agent.
        media, label = await self._extract_media(token, msg)
        if media and not text:
            text = label   # what the Inbox and history will show

        # A human owns this conversation (or the bot is off): record the message
        # and ping the operator, otherwise the customer waits on a silent chat.
        if conv.status == "operator" or not cfg.bot_enabled:
            # Yorliq faylni yuklab olishga bog'liq bo'lmasin: yuklab olish
            # yiqilsa ham (tarmoq, hajm) mijoz nima yuborgani Inboxda
            # ko'rinsin, bo'sh pufakcha emas.
            shown = text or label or _media_kind_label(msg)
            await repo.add_message(session, tenant.id, conv, "user", shown)
            from app.services import notify_service
            await notify_service.notify_customer_waiting(
                session, tenant, cfg, conv, shown,
                voice_file_id=(msg.get("voice") or {}).get("file_id"),
            )

            # Uzatilgan, lekin hech kim javob bermayapti: mijoz jim chatda
            # kutib qolmasin. Fon vazifasi ham shuni kuzatadi (contact_reminder),
            # bu yerda esa mijoz o'zi yozganda tezroq ishlaydi — ikki marta
            # yuborilmasligi bazadagi claim bilan kafolatlanadi.
            if conv.status == "operator":
                now = datetime.now(timezone.utc)
                history = await repo.recent_messages(session, tenant.id, conv.id, limit=10)
                if (contact_reminder_due(history, cfg.contact_phone, now)
                        and await repo.claim_contact_reminder(session, tenant.id, conv.id, now)):
                    note = contact_fallback_text(cfg.contact_phone, cfg.ai_language).strip()
                    await self.send_message(
                        token, chat_id, note, business_connection_id=business_connection_id
                    )
                    await repo.add_message(session, tenant.id, conv, "assistant", note)
                    logger.info("Operator jim: aloqa raqami berildi, conv=%s", conv.id)
            return

        if not text and not media:
            return  # sticker, location, etc. — nothing to act on

        # Haqorat: birinchisiga ogohlantirish, ikkinchisiga blok. Bu qaror
        # ham kod darajasida — model kayfiyatiga qarab bir mijozni kechirib,
        # boshqasini bloklab qo'yishi mumkin emas.
        from app.services import profanity
        if profanity.hits(text):
            conv.abuse_count = (conv.abuse_count or 0) + 1
            first = conv.abuse_count == 1
            reply = (profanity.warning_text(cfg.ai_language) if first
                     else profanity.block_text(cfg.ai_language))
            if not first:
                conv.blocked_at = datetime.now(timezone.utc)
                conv.status = "closed"
            await repo.add_message(session, tenant.id, conv, "user", text)
            await repo.add_message(session, tenant.id, conv, "assistant", reply)
            await session.commit()
            await self.send_message(token, chat_id, reply, business_connection_id=business_connection_id)
            if not first:
                # Blok — pul yo'qotilishi mumkin bo'lgan qaror, jamoa buni
                # ko'rib, kerak bo'lsa paneldan bekor qilsin.
                from app.services import notify_service
                await notify_service.notify_blocked(session, tenant, cfg, conv)
            logger.warning("Haqorat (%s-marta): tenant=%s conv=%s%s",
                           conv.abuse_count, tenant.id, conv.id,
                           " — BLOKLANDI" if not first else "")
            return

        # Manipulyatsiya urinishi modelga umuman bormaydi. Sabab: promptdagi
        # qoida model *ko'pincha* bajaradigan maslahat, kafolat emas — sinovda
        # u aniq ko'rsatmani ikki marta e'tiborsiz qoldirgan. Bu yerda javob
        # kod darajasida, ya'ni har safar bir xil.
        from app.services import guard
        threat = guard.detect(text)
        if threat:
            reply = guard.reply_for(threat, cfg.ai_language)
            await repo.add_message(session, tenant.id, conv, "user", text)
            await repo.add_message(session, tenant.id, conv, "assistant", reply)
            await self.send_message(token, chat_id, reply, business_connection_id=business_connection_id)

            reason = guard.handoff_reason(threat)
            # Bir suhbatda bir marta: qayta-qayta urinish jamoani ko'mib
            # tashlamasin va ular kanalga befarq bo'lib qolmasin.
            if reason and conv.status != "operator":
                conv.status = "operator"
                conv.handoff_reason = reason
                await session.commit()
                from app.services import notify_service
                await notify_service.notify_handoff(session, tenant, cfg, conv, reason)
            else:
                await session.commit()
            logger.warning("Manipulyatsiya urinishi (%s): tenant=%s conv=%s", threat, tenant.id, conv.id)
            return

        # This is the slow part — tool rounds plus retries when the model is
        # busy — so it is the only part worth showing "typing…" for.
        async with self.typing(token, chat_id, business_connection_id):
            resp = await ai_agent.generate_response(
                session,
                tenant,
                conv,
                text,
                user_name,
                media=media,
                source_update_id=source_update_id,
            )
        if resp.suppress_send:
            # 2-marta ketma-ket mavzudan tashqari savol — Inboxda ko'rinadi
            # (generate_response saqlab qo'ygan), lekin mijozga yuborilmaydi.
            logger.info("Mavzudan chiqish, javob yuborilmadi: tenant=%s conv=%s", tenant.id, conv.id)
            return
        await self.send_message(token, chat_id, resp.reply_text, business_connection_id=business_connection_id)
        await self._send_requested_photos(session, tenant, token, chat_id, resp, business_connection_id)

    async def _handle_group_message(self, session, tenant, token, msg, chat_id, text):
        """Pairing commands, and staff answering a customer by replying here.

        The AI still stays out of groups. What a group IS good for is the
        answer itself: a shop that lives in Telegram should not have to open a
        panel to reply, so a reply to our "operator kerak" alert is relayed to
        the customer it was about.
        """
        if await self._relay_staff_reply(session, tenant, token, msg, chat_id, text):
            return

        if not _is_pair_command(text):
            return

        parts = text.split()
        if len(parts) < 2:
            await self.send_message(
                token, chat_id,
                "Foydalanish: `/ulash <kod>`\n"
                "Kodni panelda *Sozlamalar → Boshqa ulanishlar → Integratsiyalar* bo'limidan oling."
            )
            return

        title = msg["chat"].get("title", "Guruh")
        reply = await self._try_pair(session, tenant, chat_id, "group", title, text)
        await self.send_message(
            token, chat_id,
            reply or "❌ Kod noto'g'ri yoki eskirgan.\n"
                     "Panelda *Sozlamalar → Boshqa ulanishlar → Integratsiyalar* bo'limidan yangi kod oling."
        )

    async def _relay_staff_reply(self, session, tenant, token, msg, chat_id, text) -> bool:
        """A reply to our alert = an answer for that customer. Pass it on.

        Telegram delivers replies to the bot's own messages even with privacy
        mode on, so this needs nothing switched on in BotFather and the bot
        still cannot read the rest of the group's conversation.

        Media travels by file_id: Telegram already holds the file, so the same
        id can be sent straight back out without downloading and re-uploading.
        """
        replied = msg.get("reply_to_message") or {}
        if not replied.get("message_id"):
            return False

        conv = await repo.conversation_by_alert(
            session, tenant.id, chat_id, str(replied["message_id"])
        )
        if not conv:
            return False

        bc_id = conv.telegram_business_connection_id
        caption = text or ""
        sent = False
        kind = ""

        if msg.get("photo"):
            file_id = msg["photo"][-1]["file_id"]
            sent = await self.send_photo(
                token, conv.external_id, file_id, caption or None, business_connection_id=bc_id
            )
            kind = "📷 rasm"
        elif msg.get("document"):
            sent = await self.send_document(
                token, conv.external_id, msg["document"]["file_id"], caption or None,
                business_connection_id=bc_id,
            )
            kind = "📎 fayl"
        elif msg.get("voice"):
            sent = await self.send_voice(
                token, conv.external_id, msg["voice"]["file_id"], caption or None,
                business_connection_id=bc_id,
            )
            kind = "🎤 ovozli xabar"
        elif caption:
            sent = await self.send_message(
                token, conv.external_id, caption, business_connection_id=bc_id
            )
        else:
            # Stiker, video va boshqalar — hozircha uzatilmaydi, lekin xodim
            # jim qolmasin: nima bo'lganini aniq aytamiz.
            await self.send_message(
                token, chat_id,
                "⚠️ Bu turdagi xabar hozircha uzatilmaydi. "
                "Matn, rasm, fayl yoki ovozli xabar yuboring.",
            )
            return True

        if not sent:
            await self.send_message(token, chat_id, "❌ Mijozga yuborib bo'lmadi. Qayta urinib ko'ring.")
            return True

        # Inboxda ham, "operator jim" soatida ham shu javob hisobga olinsin.
        await repo.add_message(
            session, tenant.id, conv, "operator", " ".join(filter(None, [kind, caption]))
        )
        await repo.release_contact_reminder(session, tenant.id, conv.id)

        who = " ".join(filter(None, [msg.get("from", {}).get("first_name"),
                                     msg.get("from", {}).get("last_name")])) or "Xodim"
        await self.send_message(token, chat_id, f"✅ *{who}*ning javobi mijozga yuborildi.")
        logger.info("Guruhdan javob uzatildi: tenant=%s conv=%s", tenant.id, conv.id)
        return True

    async def _extract_media(self, token: str, msg: dict):
        """Download a photo or voice note. Returns (parts, human label)."""
        # Telegram sends several photo sizes; the last is the largest
        if msg.get("photo"):
            data = await self.download_file(token, msg["photo"][-1]["file_id"])
            if data:
                return [{"data": data, "mime_type": "image/jpeg"}], "📷 [rasm yubordi]"

        voice = msg.get("voice") or msg.get("audio")
        if voice:
            data = await self.download_file(token, voice["file_id"])
            if data:
                mime = voice.get("mime_type") or "audio/ogg"
                return [{"data": data, "mime_type": mime}], "🎤 [ovozli xabar]"

        if msg.get("video_note"):
            data = await self.download_file(token, msg["video_note"]["file_id"])
            if data:
                return [{"data": data, "mime_type": "video/mp4"}], "🎥 [video xabar]"

        return [], ""

    async def _send_requested_photos(self, session, tenant, token, chat_id, resp, business_connection_id=None):
        """Deliver any product images the agent asked for."""
        photos = getattr(resp, "photos", None) or []
        if not photos:
            return
        if len(photos) == 1:
            p = photos[0]
            await self.send_photo(
                token, chat_id, p["url"], p.get("caption"),
                business_connection_id=business_connection_id,
            )
        else:
            ok = await self.send_media_group(token, chat_id, photos, business_connection_id=business_connection_id)
            if not ok:                      # album can fail on a bad URL — fall back
                for p in photos[:4]:
                    await self.send_photo(
                        token, chat_id, p["url"], p.get("caption"),
                        business_connection_id=business_connection_id,
                    )

    async def _handle_callback(self, session, tenant, token, query):
        chat_id = str(query["message"]["chat"]["id"])
        data = query.get("data", "")
        frm = query.get("from", {})
        user_name = frm.get("first_name", "Mijoz")
        callback_id = query.get("id")

        # Team confirming an order from the orders group
        if data.startswith("confirm:"):
            from app.services import group_service
            who = " ".join(filter(None, [frm.get("first_name"), frm.get("last_name")]))
            if frm.get("username"):
                who = f"{who} (@{frm['username']})".strip()
            ok, message = await group_service.confirm_order(
                session, tenant, data.split(":", 1)[1], who or "Xodim"
            )
            # show_alert on refusal so the second tapper actually notices
            await self.answer_callback(token, callback_id, message, alert=not ok)
            return

        # A button tapped inside a business chat: Telegram doesn't add a top-level
        # business_connection_id to CallbackQuery, but the message it's attached
        # to (a Message) carries one — same field used everywhere else.
        bc_id = (query.get("message") or {}).get("business_connection_id")

        conv = await repo.get_or_create_conversation(
            session, tenant.id, "telegram", chat_id, customer_name=user_name
        )
        if bc_id and conv.telegram_business_connection_id != bc_id:
            conv.telegram_business_connection_id = bc_id
            await session.commit()
        if callback_id:
            await self.answer_callback(token, callback_id)

        if data == "btn_catalog":
            products = await repo.list_products(session, tenant.id)
            if not products:
                await self.send_message(token, chat_id, "Katalog hozircha bo'sh.", business_connection_id=bc_id)
                return
            reply = "🛍 **Katalog:**\n\n"
            for p in products[:15]:
                reply += f"• **{p.name}** — {p.price:,.0f} {p.currency}\n"
            reply += "\nXarid uchun mahsulot nomini yozing!"
            await self.send_message(token, chat_id, reply, business_connection_id=bc_id)

        elif data == "btn_operator":
            conv.status = "operator"
            conv.handoff_reason = "Mijoz operator tugmasini bosdi"
            await session.commit()

            from app.services import notify_service
            cfg = await repo.get_settings(session, tenant.id)
            notified = await notify_service.notify_handoff(
                session, tenant, cfg, conv, conv.handoff_reason
            )
            # Nobody was reached: do not promise a call back that no one will
            # make — hand over the shop's own number instead. Same wording the
            # AI path appends, so the customer gets one answer either way.
            # Claim first, so a second tap (and the sweeper half an hour later)
            # do not each repeat the number.
            reply = "👨‍💼 Operatorga xabar berdim! Tez orada javob berishadi."
            if not notified:
                reply = "👨‍💼 So'rovingiz qabul qilindi."
                note = contact_fallback_text(cfg.contact_phone, cfg.ai_language)
                if note and await repo.claim_contact_reminder(
                    session, tenant.id, conv.id, datetime.now(timezone.utc)
                ):
                    reply += note
                else:
                    reply += " Operatorimiz tez orada bog'lanadi."
            await self.send_message(token, chat_id, reply, business_connection_id=bc_id)
            # Inboxda mijoz ko'rgan narsaning o'zi tursin.
            await repo.add_message(session, tenant.id, conv, "assistant", reply)


bot_service = TelegramBotService()
