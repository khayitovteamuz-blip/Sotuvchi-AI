import logging
import httpx
from typing import Dict, Any, Optional
from app.core.config import settings
from app.services.ai_agent import ai_agent
from app.core.database import db

logger = logging.getLogger("bot_service")


class TelegramBotService:
    def __init__(self):
        self.token = settings.TELEGRAM_BOT_TOKEN
        self.api_url = f"https://api.telegram.org/bot{self.token}"

    def is_configured(self) -> bool:
        return bool(self.token and len(self.token) > 10)

    async def send_message(
        self,
        chat_id: str,
        text: str,
        reply_markup: Optional[Dict[str, Any]] = None,
        parse_mode: str = "Markdown"
    ) -> bool:
        if not self.is_configured():
            logger.info("Telegram bot token sozlanmagan.")
            return False

        url = f"{self.api_url}/sendMessage"
        payload = {
            "chat_id": chat_id,
            "text": text,
            "parse_mode": parse_mode
        }
        if reply_markup:
            payload["reply_markup"] = reply_markup

        try:
            async with httpx.AsyncClient(timeout=10.0) as client:
                resp = await client.post(url, json=payload)
                return resp.status_code == 200
        except Exception as e:
            logger.error(f"Telegram-ga xabar yuborishda xatolik: {e}")
            return False

    async def handle_update(self, update: Dict[str, Any]):
        """Process incoming webhook update from Telegram"""
        if "message" in update:
            msg = update["message"]
            chat_id = str(msg["chat"]["id"])
            user_name = msg.get("from", {}).get("first_name", "Mijoz")
            text = msg.get("text", "")

            if text == "/start":
                welcome_text = (
                    f"Assalomu alaykum, {user_name}! 👋\n"
                    f"Men **Sotuvchi AI** — virtual sotuv konsultantingizman.\n\n"
                    f"Sizga eng mos va sifatli mahsulotlarni tanlashda hamda buyurtmani tezkor rasmiylashtirishda yordam beraman. Nima xarid qilishni rejalashtiryapsiz?"
                )
                keyboard = {
                    "inline_keyboard": [
                        [{"text": "🛍 Katalog", "callback_data": "btn_catalog"}, {"text": "📦 Buyurtmalarim", "callback_data": "btn_orders"}],
                        [{"text": "📞 Operator chaqirish", "callback_data": "btn_operator"}, {"text": "ℹ️ Yordam", "callback_data": "btn_help"}]
                    ]
                }
                await self.send_message(chat_id, welcome_text, reply_markup=keyboard)
                return

            # Normal chat message -> Pass to AI Agent
            session_id = f"tg-{chat_id}"
            response = ai_agent.generate_response(
                session_id=session_id,
                user_message=text,
                user_name=user_name,
                telegram_id=chat_id
            )

            # Send AI reply
            await self.send_message(chat_id, response.reply_text)

        elif "callback_query" in update:
            query = update["callback_query"]
            chat_id = str(query["message"]["chat"]["id"])
            data = query.get("data", "")
            user_name = query.get("from", {}).get("first_name", "Mijoz")

            if data == "btn_catalog":
                products = db.get_products()
                reply = "🛍 **Bizning Sara Mahsulotlar Katalogimiz:**\n\n"
                for p in products:
                    reply += f"• **{p.name}**\n💵 Narxi: {p.price:,.0f} UZS\n📝 {p.description}\n\n"
                reply += "Xarid qilish yoki savol berish uchun mahsulot nomini yozing!"
                await self.send_message(chat_id, reply)

            elif data == "btn_orders":
                orders = [o for o in db.get_orders() if o.telegram_id == chat_id]
                if not orders:
                    await self.send_message(chat_id, "Sizda hali rasmiylashtirilgan buyurtmalar mavjud emas. Xaridni hoziroq boshlashingiz mumkin!")
                else:
                    reply = "📦 **Sizning Buyurtmalaringiz:**\n\n"
                    for o in orders:
                        reply += f"🆔 `{o.id}` | {o.status}\n💰 Summa: {o.total_amount:,.0f} UZS | Sana: {o.created_at}\n\n"
                    await self.send_message(chat_id, reply)

            elif data == "btn_operator":
                await self.send_message(chat_id, "👨‍💼 Operatorga xabar yuborildi! Tez orada mutaxassisimiz siz bilan muloqotga kirishadi.")

            elif data == "btn_help":
                await self.send_message(chat_id, "ℹ️ **Yo'riqnoma:**\nSiz AI Sotuvchi bilan xuddi tirik sotuvchi kabi muloqot qilishingiz mumkin. Shunchaki o'zingizni qiziqtirgan savolni yoki mahsulot nomini yozing.")


bot_service = TelegramBotService()
