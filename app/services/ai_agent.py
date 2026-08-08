import re
import random
import logging
from typing import List, Tuple, Optional
from app.models.schema import Product, Order, OrderItem, ChatMessage, ChatResponse
from app.core.database import db
from app.core.config import settings
from app.services.sheets_service import sheets_service

logger = logging.getLogger("ai_agent")


class AISalesAgent:
    def __init__(self):
        pass

    def _build_context_prompt(self, session_id: str, current_message: str) -> str:
        products = db.get_products()
        catalog_str = "MAHSULOTLAR KATALOGI (Sotuvda bor):\n"
        for p in products:
            status = "Mavjud" if p.in_stock else "Tugagan"
            catalog_str += f"- ID: {p.id} | Nomi: {p.name} | Narxi: {p.price:,.0f} {p.currency} | Kategoriya: {p.category} | Holat: {status}\n  Tavsif: {p.description}\n"

        history = db.get_session_history(session_id)
        history_str = "SUHBAT TARIXI:\n"
        for msg in history[-6:]:  # Last 6 messages
            sender_name = "Mijoz" if msg.sender == "user" else "Sotuvchi AI"
            history_str += f"{sender_name}: {msg.text}\n"

        system_instruction = db.settings.system_prompt

        full_prompt = f"""{system_instruction}

{catalog_str}

{history_str}
Mijoz: {current_message}
Sotuvchi AI:"""
        return full_prompt

    def generate_response(self, session_id: str, user_message: str, user_name: str = "Mijoz", telegram_id: Optional[str] = None) -> ChatResponse:
        # Save user message
        user_msg_obj = ChatMessage(id=f"msg-{random.randint(1000,9999)}", session_id=session_id, sender="user", text=user_message)
        db.add_chat_message(user_msg_obj)

        products = db.get_products()
        provider = db.settings.ai_provider
        gemini_key = settings.GEMINI_API_KEY
        anthropic_key = settings.ANTHROPIC_API_KEY

        reply_text = ""
        intent = "general_query"
        recommended_products: List[Product] = []
        order_draft: Optional[Order] = None

        # Detect intent and recommended products based on user query
        query_lower = user_message.lower()

        # Find matching products
        for p in products:
            if any(term in query_lower for term in p.name.lower().split()) or p.category.lower() in query_lower:
                if p not in recommended_products:
                    recommended_products.append(p)

        # Intent detection
        if any(w in query_lower for w in ["salom", "assalomu alaykum", "hayrli", "privet", "sardor"]):
            intent = "greeting"
        elif any(w in query_lower for w in ["narx", "qancha", "necha pul", "qimmatcha", "aksiya", "chegirma", "katalog"]):
            intent = "query"
        elif any(w in query_lower for w in ["olmoqchiman", "xarid", "sotib olaman", "buyurtma", "zakaz", "olaman"]):
            intent = "order_intent"
        elif any(w in query_lower for w in ["qimmat", "boshqa joyda arzon", "kafolat", "ishonch"]):
            intent = "objection"

        # Try LLM Generation if API Keys available
        if provider == "gemini" and gemini_key:
            reply_text = self._call_gemini(session_id, user_message)
        elif provider == "anthropic" and anthropic_key:
            reply_text = self._call_anthropic(session_id, user_message)

        # Fallback AI Sales Engine if LLM key is not provided or fails
        if not reply_text:
            reply_text = self._fallback_uzbek_sales_engine(user_message, intent, recommended_products, products, session_id, user_name)

        # Check for order detail collection (Phone number, Name, Product selection)
        order_draft = self._check_and_create_order(session_id, user_message, user_name, telegram_id, products)
        if order_draft:
            intent = "closing"
            reply_text += f"\n\n🎉 **Buyurtmangiz muvaffaqiyatli qabul qilindi!**\n🆔 Buyurtma ID: `{order_draft.id}`\n💰 Jami summa: {order_draft.total_amount:,.0f} UZS\n📞 Bog'lanish uchun: {order_draft.customer_phone}\n\nTez orada operatorimiz siz bilan bog'lanadi!"

        # Save assistant message
        ai_msg_obj = ChatMessage(id=f"msg-{random.randint(1000,9999)}", session_id=session_id, sender="assistant", text=reply_text)
        db.add_chat_message(ai_msg_obj)

        return ChatResponse(
            session_id=session_id,
            reply_text=reply_text,
            intent=intent,
            recommended_products=recommended_products[:3],
            order_draft=order_draft
        )

    def _call_gemini(self, session_id: str, user_message: str) -> str:
        try:
            from google import genai
            client = genai.Client(api_key=settings.GEMINI_API_KEY)
            prompt = self._build_context_prompt(session_id, user_message)
            response = client.models.generate_content(
                model='gemini-2.5-flash',
                contents=prompt,
            )
            return response.text
        except Exception as e:
            logger.error(f"Gemini API Error: {e}")
            return ""

    def _call_anthropic(self, session_id: str, user_message: str) -> str:
        try:
            import anthropic
            client = anthropic.Anthropic(api_key=settings.ANTHROPIC_API_KEY)
            prompt = self._build_context_prompt(session_id, user_message)
            response = client.messages.create(
                model="claude-3-5-sonnet-20241022",
                max_tokens=500,
                messages=[{"role": "user", "content": prompt}]
            )
            return response.content[0].text
        except Exception as e:
            logger.error(f"Anthropic API Error: {e}")
            return ""

    def _fallback_uzbek_sales_engine(
        self,
        user_message: str,
        intent: str,
        matched_products: List[Product],
        all_products: List[Product],
        session_id: str,
        user_name: str
    ) -> str:
        """High-converting, natural Uzbek Sales Dialogue Engine for Fallback/Demo mode"""
        if intent == "greeting":
            prod_names = ", ".join([p.name for p in all_products[:3]])
            return f"Assalomu alaykum, {user_name}! 👋 'Sotuvchi AI' do'konimizga xush kelibsiz! Bugun sizga qaysi mahsulotni tanlashda yordam beray? Bizda hozirda {prod_names} va boshqa ko'plab premium mahsulotlar mavjud!"

        if matched_products:
            p = matched_products[0]
            if intent == "query":
                return f"✨ **{p.name}** haqida ma'lumot:\n\n📝 Tavsif: {p.description}\n💵 Narxi: **{p.price:,.0f} UZS**\n📦 Omborimizda: {'Mavjud (Zudlik bilan yetkazib beramiz)' if p.in_stock else 'Tugagan'}\n\nUshbu model rasmiy kafolat bilan beriladi. Xarid qilishni xohlaysizmi? Buyurtma berish uchun ismingiz va telefon raqamingizni qoldiring!"

            if intent == "objection":
                return f"Tushunaman, narx muhim omil. Lekin **{p.name}** o'z segmentida eng sifatli materiallar va rasmiy 1 yillik kafolat bilan ta'minlangan. Bugun buyurtma bersangiz, yetkazib berish va sovg'a sifatida aksessuar ham qo'shib beramiz! Buyurtmani rasmiylashtiraylikmi?"

            if intent == "order_intent":
                return f"Ajoyib tanlov! 🎯 **{p.name}** ({p.price:,.0f} UZS) buyurtmasini rasmiylashtirish uchun iltimos:\n1. Ism-familiyangiz\n2. Telefon raqamingiz (+998XX...)\n3. Yetkazib berish manzilingizni yuboring."

        # Default smart sales response
        cat_str = "\n".join([f"• **{p.name}** — {p.price:,.0f} UZS" for p in all_products])
        return f"Sizning so'rovingiz bo'yicha bizdagi eng ommabop mahsulotlar katalogini taklif qilaman:\n\n{cat_str}\n\nQaysi birining xususiyatlari va narxlari bilan batafsilroq tanishishni xohlaysiz?"

    def _check_and_create_order(
        self,
        session_id: str,
        user_message: str,
        user_name: str,
        telegram_id: Optional[str],
        products: List[Product]
    ) -> Optional[Order]:
        """Detect phone number and product intent to create an Order"""
        phone_match = re.search(r'(\+?998[\s\-]?\d{2}[\s\-]?\d{3}[\s\-]?\d{2}[\s\-]?\d{2})|(\d{9})', user_message)
        if not phone_match:
            return None

        phone_num = phone_match.group(0)

        # Determine matched product from history or current message
        history = db.get_session_history(session_id)
        full_text = " ".join([m.text for m in history]) + " " + user_message

        selected_product = products[0]
        for p in products:
            if p.name.lower() in full_text.lower():
                selected_product = p
                break

        order_id = f"ORD-{random.randint(10000, 99999)}"
        order_item = OrderItem(
            product_id=selected_product.id,
            product_name=selected_product.name,
            quantity=1,
            unit_price=selected_product.price
        )

        order = Order(
            id=order_id,
            customer_name=user_name if user_name != "Mijoz" else "Telegram Xaridori",
            customer_phone=phone_num,
            telegram_id=telegram_id,
            items=[order_item],
            total_amount=selected_product.price,
            status="Yangi",
            delivery_address="Toshkent shahri (muloqotda ko'rsatilgan)",
            notes="AI Sotuvchi orqali avtomatik shakllantirilgan buyurtma"
        )

        # Save to database
        db.add_order(order)

        # Sync with Google Sheets if connected
        sheets_service.log_order(order)

        return order


ai_agent = AISalesAgent()
