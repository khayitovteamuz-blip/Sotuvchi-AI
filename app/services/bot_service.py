"""
Telegram bot service — tenant-scoped.

Each business connects its OWN bot token (stored on the tenant). Updates arrive
at /api/bot/webhook/{tenant_id}; replies are sent with that tenant's token.
"""
import json
import logging
from typing import Any, Dict, Optional

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import repo
from app.db.models import Tenant
from app.services.ai_agent import ai_agent
from app.services.storage_service import local_path as _local_photo

logger = logging.getLogger("bot_service")
TELEGRAM_API = "https://api.telegram.org/bot{token}"

# Inline media must fit in the model request; Telegram voice/photos are far
# smaller than this in practice, so the cap only guards against odd uploads.
MAX_MEDIA_BYTES = 15 * 1024 * 1024


def _is_markup_error(data: dict) -> bool:
    """Did Telegram reject the text because of its Markdown, not its content?"""
    desc = str(data.get("description", "")).lower()
    return "parse" in desc and "entit" in desc


class TelegramBotService:
    async def _post_message(
        self, token: str, chat_id: str, text: str,
        reply_markup: Optional[Dict[str, Any]], parse_mode: Optional[str], timeout: float,
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
    ) -> bool:
        if not token:
            return False
        return await self._post_message(token, chat_id, text, reply_markup, parse_mode, 10.0) is not None

    async def send_message_full(
        self, token: str, chat_id: str, text: str,
        reply_markup: Optional[Dict[str, Any]] = None, parse_mode: str = "Markdown",
    ) -> Optional[dict]:
        """Like send_message but returns the sent message — we need its id to
        edit the receipt once someone confirms."""
        if not token:
            return None
        return await self._post_message(token, chat_id, text, reply_markup, parse_mode, 15.0)

    async def edit_message(
        self, token: str, chat_id: str, message_id: str, text: str,
        reply_markup: Optional[Dict[str, Any]] = None, parse_mode: str = "Markdown",
    ) -> bool:
        payload = {"chat_id": chat_id, "message_id": int(message_id),
                   "text": text, "parse_mode": parse_mode}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
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
    ) -> bool:
        """A photo message carries a caption, not text — editMessageText fails on it."""
        payload = {"chat_id": chat_id, "message_id": int(message_id),
                   "caption": caption[:1024], "parse_mode": "Markdown"}
        if reply_markup is not None:
            payload["reply_markup"] = reply_markup
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
        self, token: str, chat_id: str, photo_url: str, caption: Optional[str] = None
    ) -> bool:
        """Send a product image, by URL or from our own disk."""
        return await self.send_photo_full(token, chat_id, photo_url, caption) is not None

    async def send_photo_full(
        self, token: str, chat_id: str, photo: str,
        caption: Optional[str] = None, reply_markup: Optional[Dict[str, Any]] = None,
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
        if reply_markup:
            payload["reply_markup"] = json.dumps(reply_markup)

        local = _local_photo(photo)
        files = None
        if local is None:
            payload["photo"] = photo
        else:
            files = {"photo": (local.name, local.read_bytes())}

        try:
            async with httpx.AsyncClient(timeout=25.0) as client:
                url = f"{TELEGRAM_API.format(token=token)}/sendPhoto"
                resp = (await client.post(url, data=payload, files=files) if files
                        else await client.post(url, json={**payload, "photo": photo,
                                                          **({"reply_markup": reply_markup} if reply_markup else {})}))
                data = resp.json()
                if not data.get("ok"):
                    logger.warning(f"sendPhoto failed: {str(data)[:180]}")
                    return None
                return data["result"]
        except Exception as e:
            logger.error(f"Telegram sendPhoto error: {e}")
            return None

    async def send_media_group(self, token: str, chat_id: str, items: list) -> bool:
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

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                url = f"{TELEGRAM_API.format(token=token)}/sendMediaGroup"
                if files:
                    resp = await client.post(
                        url,
                        data={"chat_id": chat_id, "media": json.dumps(media)},
                        files=files,
                    )
                else:
                    resp = await client.post(url, json={"chat_id": chat_id, "media": media})
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
                "allowed_updates": ["message", "callback_query", "my_chat_member"],
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
        if "message" in update:
            await self._handle_message(session, tenant, token, update["message"])
        elif "callback_query" in update:
            await self._handle_callback(session, tenant, token, update["callback_query"])

    async def _handle_message(self, session, tenant, token, msg):
        chat_id = str(msg["chat"]["id"])
        user_name = msg.get("from", {}).get("first_name", "Mijoz")
        # A photo's text arrives as "caption", not "text"
        text = msg.get("text") or msg.get("caption") or ""

        # Group chats are team channels, never customer conversations
        if msg["chat"].get("type") in ("group", "supergroup"):
            await self._handle_group_message(session, tenant, token, msg, chat_id, text)
            return

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
        # Keep the Telegram handle: the team needs a way back to the customer
        # when a phone number is wrong or unreachable.
        uname = msg.get("from", {}).get("username")
        if uname and conv.customer_username != uname:
            conv.customer_username = uname
            await session.commit()

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
            await group_service.attach_payment_slip(session, tenant, conv.id, file_id)

        # Photo / voice: customers here often show a product or just talk.
        # Gemini reads both, so hand the bytes straight to the agent.
        media, label = await self._extract_media(token, msg)
        if media and not text:
            text = label   # what the Inbox and history will show

        # A human owns this conversation (or the bot is off): record the message
        # and ping the operator, otherwise the customer waits on a silent chat.
        if conv.status == "operator" or not cfg.bot_enabled:
            await repo.add_message(session, tenant.id, conv, "user", text or label)
            from app.services import notify_service
            await notify_service.notify_customer_waiting(session, tenant, cfg, conv, text or label)
            return

        if not text and not media:
            return  # sticker, location, etc. — nothing to act on

        resp = await ai_agent.generate_response(
            session, tenant, conv, text, user_name, media=media
        )
        await self.send_message(token, chat_id, resp.reply_text)
        await self._send_requested_photos(session, tenant, token, chat_id, resp)

    async def _handle_group_message(self, session, tenant, token, msg, chat_id, text):
        """Only the pairing command matters in a group; the AI stays out."""
        from app.services import group_service

        if not text.startswith("/guruh"):
            return

        parts = text.split()
        if len(parts) < 3:
            await self.send_message(
                token, chat_id,
                "Foydalanish: `/guruh <tur> <kod>`\n"
                "Turlari: `buyurtmalar`, `ishchi`, `operatorlar`\n"
                "Kodni paneldagi *Integratsiyalar* bo'limidan oling."
            )
            return

        reply = await group_service.try_pair_group(
            session, tenant, parts[1], parts[2], chat_id, msg["chat"].get("title", ""),
        )
        if reply:
            await self.send_message(token, chat_id, reply)

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

    async def _send_requested_photos(self, session, tenant, token, chat_id, resp):
        """Deliver any product images the agent asked for."""
        photos = getattr(resp, "photos", None) or []
        if not photos:
            return
        if len(photos) == 1:
            p = photos[0]
            await self.send_photo(token, chat_id, p["url"], p.get("caption"))
        else:
            ok = await self.send_media_group(token, chat_id, photos)
            if not ok:                      # album can fail on a bad URL — fall back
                for p in photos[:4]:
                    await self.send_photo(token, chat_id, p["url"], p.get("caption"))

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

        conv = await repo.get_or_create_conversation(
            session, tenant.id, "telegram", chat_id, customer_name=user_name
        )
        if callback_id:
            await self.answer_callback(token, callback_id)

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
