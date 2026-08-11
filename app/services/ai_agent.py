"""
AI Sales Agent — tenant-scoped, Postgres-backed, tool-calling.

The model does not answer from the prompt alone: it calls tools (search_product,
check_stock, create_order, calc_delivery, handoff_to_human) that read and write
the tenant's real Postgres rows. Prices, stock and order ids therefore cannot be
hallucinated — that is the difference between this and a plain chatbot.

Falls back to a keyword sales engine when no API key is configured.
"""
import asyncio
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db import repo
from app.db.models import Conversation, Product, Tenant, TenantSettings
from app.models.schema import ChatResponse
from app.services import ai_tools

logger = logging.getLogger("ai_agent")

MAX_TOOL_ROUNDS = 5   # guard against a model looping on tools forever
MAX_RETRIES = 2       # retries on transient 429/503 from the API
MAX_RETRY_WAIT = 25.0 # seconds; longer than this we give up and use the fallback


def _new_usage() -> Dict[str, int]:
    return {"total": 0, "prompt": 0, "output": 0}


def _add_usage(usage: Dict[str, int], resp) -> None:
    """Accumulate one response's token counts.

    Input and output are kept apart because they are billed at different rates —
    a single blended total cannot be priced correctly.
    """
    try:
        um = resp.usage_metadata
        usage["total"] += um.total_token_count or 0
        usage["prompt"] += um.prompt_token_count or 0
        usage["output"] += um.candidates_token_count or 0
    except Exception:
        pass

STYLE = """
GAPIRISH USLUBI (juda muhim):
- Mijozga ISMI bilan murojaat qiling va hurmat so'zini qo'shing:
  erkak ismi bo'lsa "aka", ayol ismi bo'lsa "opa".
  Masalan: "Bekzod aka", "Dilnoza opa".
  Jinsini o'zbek ismidan aniqlang. Aniq bo'lmasa — faqat ismini ishlating.
  Har javobda emas, tabiiy joyda ishlating (odatda javob boshida).
- Tirik odamdek, oddiy so'zlashuv tilida gapiring. Rasmiy kanselyariya tilidan
  qoching: "ushbu", "mazkur", "tashkil qiladi", "ma'lum qilamanki" — YOZMANG.
  Buning o'rniga: "bu", "narxi", "bor", "chiroyli".
- Do'stona va samimiy bo'ling, xuddi do'kondagi yaxshi sotuvchi kabi.
  Qisqa gaplar. Ba'zan emoji (ko'p emas, 1-2 ta).
- "Sizga qanday yordam bera olaman?" kabi robot iboralarni ishlatmang.
  Oddiy qiling: "Nima qidiryapsiz?", "Qaysi biri yoqdi?"

YAXSHI misol: "Bekzod aka, AirPods Pro bor 👍 Narxi 2 950 000 so'm.
Olasizmi? Ismingiz va telefon raqamingizni tashlang."

YOMON misol (bunday YOZMANG): "Assalomu alaykum! Ushbu mahsulot bizning
katalogimizda mavjud bo'lib, uning narxi 2 950 000 so'mni tashkil qiladi."
"""

GUARDRAILS = """
QAT'IY QOIDALAR (buzilishi mumkin emas):
1. Narx, ombor qoldig'i yoki mahsulot tavsifini HECH QACHON o'zingizdan aytmang.
   Har doim avval search_product yoki check_stock funksiyasini chaqiring va faqat
   qaytgan qiymatlarni ayting.
2. Chegirma, aksiya yoki sovg'a VA'DA QILMANG. Bunday vakolatingiz yo'q.
   Mijoz chegirma so'rasa — handoff_to_human FUNKSIYASINI CHAQIRING.
   DIQQAT: "operatorga ulayman" deb YOZISH yetarli emas. Funksiyani
   chaqirmasangiz, operator hech narsa bilmaydi va mijoz javobsiz qoladi.
   Avval funksiyani chaqiring, keyin mijozga ayting.
3. Omborda yo'q mahsulotni sotmang. check_stock "in_stock: false" qaytarsa,
   muqobil mahsulot taklif qiling.
4. Buyurtma ID sini o'zingiz yaratmang — faqat create_order qaytargan ID ni ayting.
5. create_order ni faqat mijozning ISMI va TELEFON raqami bo'lsa chaqiring.
   Yo'q bo'lsa — avval mijozdan so'rang.
6. Yetkazib berish narxini calc_delivery orqali oling, taxmin qilmang.
   Agar u "known: false" qaytarsa — narx aytmang, "operatorimiz aniq narxni
   aytadi" deng.
6a. To'lov, kafolat, qaytarish, ish vaqti va shunga o'xshash do'kon qoidalari
   haqidagi HAR QANDAY savolda search_knowledge chaqiring. Bu qoidalarni
   o'zingizdan yozish — mijozga yolg'on va'da berish demakdir. Bilimlar bazasi
   bo'sh bo'lsa handoff_to_human chaqiring.
7. Javobni bilmasangiz yoki mijoz operator so'rasa — handoff_to_human
   funksiyasini chaqiring (shunchaki yozish emas!). "Bilmadim" deb qo'yib
   yubormang.
8. Qisqa va tabiiy gapiring (2-4 jumla). Har javob oxirida mijozni keyingi
   qadamga undang.
9. Texnik tafsilotlarni mijozga KO'RSATMANG: funksiya nomlari, maydon nomlari
   (in_stock, product_id, PROD-101 kabi), JSON yoki xato matnlarini yozmang.
   Ularni oddiy odam tilida ayting ("hozircha omborda tugagan").
10. Mijoz RASM yuborsa: rasmda nima borligini o'zingiz ko'rasiz. Uni tavsiflab
   o'tirmang — darhol search_product bilan katalogdan shunga o'xshashini qidiring
   va topganingizni ayting. Topilmasa, eng yaqin muqobilni taklif qiling.
11. Mijoz OVOZLI xabar yuborsa: uni eshitasiz. "Ovozingizni eshitdim" deb
   yozmang, shunchaki so'raganiga javob bering.
12. Mahsulot haqida gapirganda RASMINI ham yuboring — send_product_photo
   chaqiring. Rasm matndan ko'ra yaxshiroq sotadi. Lekin har javobda emas:
   mijoz aniq mahsulotga qiziqqanda yoki variantlarni taqqoslaganda.
13. Buyurtma rasmiylashtirilgandan keyin mijozdan TO'LOV CHEKI rasmini
   so'rang: "To'lovni amalga oshirib, chek rasmini shu yerga yuboring —
   tasdiqlangach buyurtmangiz yetkazishga chiqadi."
   Mijoz chek rasmini yuborsa — rahmat ayting va tekshiruvga
   yuborilganini bildiring. Chekni o'zingiz tasdiqlamang, bu odam ishi.
"""


class AISalesAgent:
    async def generate_response(
        self,
        session: AsyncSession,
        tenant: Tenant,
        conversation: Conversation,
        user_message: str,
        user_name: str = "Mijoz",
        media: Optional[List[Dict[str, Any]]] = None,
    ) -> ChatResponse:
        """media: [{"data": bytes, "mime_type": "image/jpeg"}] — photos or voice
        the customer sent. Gemini reads both natively."""
        tenant_id = tenant.id
        cfg = await repo.get_settings(session, tenant_id)
        history = await repo.recent_messages(session, conversation.id, limit=10)

        # A voice note or bare photo has no text — store a label so the Inbox
        # shows something meaningful instead of an empty bubble.
        stored_text = user_message or self._media_label(media)
        await repo.add_message(
            session, tenant_id, conversation, "user", stored_text,
            meta={"media": [m["mime_type"] for m in media]} if media else None,
        )

        t0 = time.monotonic()
        reply_text, model_used = "", None
        usage = _new_usage()
        tool_trace: List[Dict[str, Any]] = []

        use_gemini = cfg.ai_provider == "gemini" and settings.GEMINI_API_KEY
        if use_gemini:
            reply_text, usage, tool_trace = await self._run_gemini_with_tools(
                session, tenant_id, conversation, cfg, history, user_message, user_name, media
            )
            model_used = cfg.model_name
        elif media:
            # No key: we can't read a photo or voice note, so say so plainly
            # instead of answering as if the message was empty.
            reply_text = ("Kechirasiz, hozir rasm va ovozli xabarlarni o'qiy olmayapman. "
                          "Iltimos, matn bilan yozib yuboring 🙏")
            model_used = "fallback"

        if not reply_text:
            if media:
                # The keyword engine can't see a photo or hear a voice note —
                # answering from the (empty) text would produce nonsense.
                reply_text = ("Kechirasiz, xabaringizni ocholmadim 😔 "
                              "Iltimos, yozib yuboring yoki qaytadan urinib ko'ring.")
                model_used = model_used or "media-failed"
            else:
                products = await repo.list_products(session, tenant_id)
                intent = self._detect_intent(user_message)
                matched = self._match_products(user_message, products)
                reply_text = self._fallback(user_message, intent, matched, products, user_name, cfg)
                model_used = model_used or "fallback"

        # Safety net: models sometimes *say* they are escalating without calling
        # the tool. A promise nobody acts on is worse than no promise, so if the
        # reply announces an operator, perform the handoff for real.
        tool_trace = await self._enforce_promised_handoff(
            session, tenant_id, conversation, reply_text, tool_trace
        )

        latency_ms = int((time.monotonic() - t0) * 1000)
        intent = self._intent_from_trace(tool_trace) or self._detect_intent(user_message)

        await repo.add_message(
            session, tenant_id, conversation, "assistant", reply_text,
            intent=intent, model_name=model_used, tokens=usage["total"],
            prompt_tokens=usage["prompt"], output_tokens=usage["output"],
            latency_ms=latency_ms,
            meta={"tools": tool_trace} if tool_trace else None,
        )

        # recommend whatever the model actually looked up
        recommended = await self._recommended_from_trace(session, tenant_id, tool_trace, user_message)

        # Photos the model asked for — the channel delivers them
        photos = []
        for t in tool_trace:
            if t["name"] == "send_product_photo":
                photos.extend(t["result"].get("photos") or [])

        return ChatResponse(
            session_id=conversation.id,
            reply_text=reply_text,
            intent=intent,
            recommended_products=recommended[:3],
            order_draft=None,  # orders are persisted by the tool; see meta/tool_trace
            photos=photos,
        )

    # ─── Gemini tool-calling loop ─────────────────────────────────────────────
    async def _run_gemini_with_tools(
        self, session, tenant_id, conversation, cfg, history, user_message, user_name, media=None
    ) -> Tuple[str, Dict[str, int], List[Dict[str, Any]]]:
        try:
            from google.genai import types
        except Exception as e:
            logger.error(f"genai import failed: {e}")
            return ("", _new_usage(), [])

        client = self._client()
        if client is None:
            return ("", _new_usage(), [])

        system_instruction = self._system_instruction(cfg, conversation, user_name)

        # Build the conversation for the model
        contents: List[Any] = []
        for m in history:
            role = "user" if m.sender == "user" else "model"
            contents.append(types.Content(role=role, parts=[types.Part.from_text(text=m.text)]))

        # The customer's photo / voice note goes in as raw bytes alongside any text
        turn_parts = []
        for m in (media or []):
            turn_parts.append(types.Part.from_bytes(data=m["data"], mime_type=m["mime_type"]))
        if user_message:
            turn_parts.append(types.Part.from_text(text=user_message))
        if not turn_parts:
            turn_parts.append(types.Part.from_text(text="..."))
        contents.append(types.Content(role="user", parts=turn_parts))

        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            tools=ai_tools.tool_declarations(),
            temperature=cfg.temperature,
        )

        usage = _new_usage()
        trace: List[Dict[str, Any]] = []

        for _round in range(MAX_TOOL_ROUNDS):
            resp = await self._generate(client, cfg.model_name, contents, config)
            if resp is None:
                return ("", usage, trace)

            _add_usage(usage, resp)

            calls = list(getattr(resp, "function_calls", None) or [])
            if not calls:
                return ((resp.text or "").strip(), usage, trace)

            # Echo back the model's OWN content, not a reconstruction: thinking
            # models attach a thought_signature to functionCall parts and reject
            # the next request if it is missing.
            model_content = resp.candidates[0].content
            contents.append(model_content)

            result_parts = []
            for call in calls:
                args = dict(call.args or {})
                result = await ai_tools.execute_tool(
                    call.name, args, session, tenant_id, conversation
                )
                trace.append({"name": call.name, "args": args, "result": result})
                logger.info(f"[tool] {call.name}({args}) -> {str(result)[:160]}")
                result_parts.append(types.Part.from_function_response(name=call.name, response=result))

            contents.append(types.Content(role="user", parts=result_parts))

        # Ran out of rounds — ask for a final answer without tools
        final = await self._generate(
            client, cfg.model_name, contents,
            types.GenerateContentConfig(system_instruction=system_instruction, temperature=cfg.temperature),
        )
        if final is None:
            return ("", usage, trace)
        # This closing call used to go uncounted, so the cost panel understated
        # every conversation that exhausted its tool rounds.
        _add_usage(usage, final)
        return ((final.text or "").strip(), usage, trace)

    async def _generate(self, client, model: str, contents, config):
        """One generate_content call, retrying transient rate limits (429/503).

        The free Gemini tier is only a few requests per minute and one chat turn
        costs 2+ requests, so a short retry is the difference between a real
        answer and silently dropping to the fallback engine.
        """
        for attempt in range(MAX_RETRIES + 1):
            try:
                return await asyncio.to_thread(
                    client.models.generate_content, model=model, contents=contents, config=config
                )
            except Exception as e:
                msg = str(e)
                transient = "429" in msg or "RESOURCE_EXHAUSTED" in msg or "503" in msg or "UNAVAILABLE" in msg
                if not transient or attempt == MAX_RETRIES:
                    logger.error(f"Gemini API error ({'rate limit' if transient else 'fatal'}): {msg[:200]}")
                    return None
                wait = self._retry_delay(msg, attempt)
                if wait > MAX_RETRY_WAIT:
                    logger.error(f"Gemini rate limited, retry delay {wait}s too long — using fallback")
                    return None
                logger.warning(f"Gemini rate limited, retrying in {wait:.1f}s (attempt {attempt + 1})")
                await asyncio.sleep(wait)
        return None

    @staticmethod
    def _retry_delay(msg: str, attempt: int) -> float:
        """Honour the API's suggested retryDelay, else exponential backoff."""
        m = re.search(r"'retryDelay':\s*'(\d+(?:\.\d+)?)s'", msg) or re.search(r"retry in (\d+(?:\.\d+)?)s", msg)
        if m:
            return float(m.group(1)) + 0.5
        return 2.0 * (2 ** attempt)

    # Phrases that mean "a human will take over" — if the model says one of
    # these it has made a promise to the customer that must be kept.
    _HANDOFF_PROMISE = re.compile(
        r"operator(imiz|ga|ni|lar)?\b.*\b(ula|bog'la|boglа|xabar|yuboraman|beradi|chaqir)"
        r"|operatorga\s+(ulay|ulab|uzat)"
        r"|mutaxassis(imiz)?\s+.*(bog'lan|javob)",
        re.IGNORECASE | re.DOTALL,
    )

    async def _enforce_promised_handoff(self, session, tenant_id, conversation, reply_text, trace):
        """Execute a handoff the model promised in text but never called."""
        if any(t["name"] == "handoff_to_human" for t in trace):
            return trace
        if conversation.status != "ai" or not reply_text:
            return trace
        if not self._HANDOFF_PROMISE.search(reply_text):
            return trace

        logger.info("Model promised an operator without calling the tool — enforcing handoff")
        result = await ai_tools.execute_tool(
            "handoff_to_human",
            {"reason": "AI operatorni va'da qildi (avtomatik uzatildi)"},
            session, tenant_id, conversation,
        )
        return trace + [{"name": "handoff_to_human", "args": {"reason": "auto-enforced"}, "result": result}]

    def _client(self):
        try:
            from google import genai
            return genai.Client(api_key=settings.GEMINI_API_KEY)
        except Exception as e:
            logger.error(f"Gemini client init failed: {e}")
            return None

    def _system_instruction(self, cfg: TenantSettings, conversation: Conversation, user_name: str) -> str:
        tone = {
            "professional": "Ishonchli, lekin quruq emas — tirik odamdek gapiring.",
            "friendly": "Do'stona, iliq va samimiy — yaqin tanishingiz bilan gaplashayotgandek.",
            "concise": "Juda qisqa va aniq — 1-2 jumla, ortiqcha gap yo'q.",
        }.get(cfg.ai_tone or "friendly", "")
        lang = {
            "uz": "Har doim O'ZBEK tilida javob bering.",
            "ru": "Всегда отвечайте на РУССКОМ языке.",
            "en": "Always answer in ENGLISH.",
        }.get(cfg.ai_language or "uz", "Har doim o'zbek tilida javob bering.")

        return (
            f"Sizning ismingiz: {cfg.ai_name or 'Sotuvchi AI'}.\n"
            f"{cfg.system_prompt}\n\n{tone}\n{lang}\n"
            f"Mijozning ismi: {user_name}. Kanal: {conversation.channel}.\n"
            f"{STYLE}\n{GUARDRAILS}"
        )

    # ─── helpers ──────────────────────────────────────────────────────────────
    @staticmethod
    def _media_label(media) -> str:
        if not media:
            return ""
        mime = media[0].get("mime_type", "")
        if mime.startswith("image/"):
            return "📷 [rasm]"
        if mime.startswith("audio/"):
            return "🎤 [ovozli xabar]"
        if mime.startswith("video/"):
            return "🎥 [video]"
        return "[fayl]"

    def _intent_from_trace(self, trace) -> Optional[str]:
        names = [t["name"] for t in trace]
        if "create_order" in names:
            return "closing"
        if "handoff_to_human" in names:
            return "handoff"
        if "check_stock" in names or "search_product" in names:
            return "query"
        return None

    async def _recommended_from_trace(self, session, tenant_id, trace, user_message) -> List[Product]:
        ids = []
        for t in trace:
            r = t.get("result") or {}
            for p in (r.get("products") or []):
                if p.get("product_id"):
                    ids.append(p["product_id"])
            if r.get("product_id"):
                ids.append(r["product_id"])
        out, seen = [], set()
        for pid in ids:
            if pid in seen:
                continue
            seen.add(pid)
            p = await repo.get_product(session, tenant_id, pid)
            if p:
                out.append(p)
        if not out:
            products = await repo.list_products(session, tenant_id)
            out = self._match_products(user_message, products)
        return out

    def _detect_intent(self, msg: str) -> str:
        q = msg.lower()
        if any(w in q for w in ["salom", "assalom", "hayrli", "privet"]):
            return "greeting"
        if any(w in q for w in ["olmoqchi", "xarid", "sotib", "buyurtma", "zakaz", "olaman"]):
            return "order_intent"
        if any(w in q for w in ["qimmat", "arzon", "kafolat", "ishonch"]):
            return "objection"
        if any(w in q for w in ["narx", "qancha", "necha pul", "aksiya", "chegirma", "katalog"]):
            return "query"
        return "general_query"

    def _match_products(self, msg: str, products: List[Product]) -> List[Product]:
        q = msg.lower()
        out = []
        for p in products:
            if any(term in q for term in p.name.lower().split()) or (p.category and p.category.lower() in q):
                if p not in out:
                    out.append(p)
        return out

    # ─── fallback engine (no API key) ─────────────────────────────────────────
    def _fallback(self, msg, intent, matched, products, user_name, cfg) -> str:
        ai_name = cfg.ai_name or "Sotuvchi AI"
        if intent == "greeting":
            names = ", ".join(p.name for p in products[:3]) or "mahsulotlar"
            return (f"Assalomu alaykum, {user_name}! 👋 '{ai_name}' do'koniga xush kelibsiz! "
                    f"Bizda {names} va boshqa mahsulotlar bor. Nima tanlashda yordam beray?")
        if matched:
            p = matched[0]
            if intent == "objection":
                return (f"Tushunaman, narx muhim. **{p.name}** sifatli va rasmiy kafolat bilan. "
                        f"Batafsil shartlarni operatorimiz aytib beradi. Rasmiylashtiraymizmi?")
            if intent == "order_intent":
                return (f"Ajoyib tanlov! 🎯 **{p.name}** ({p.price:,.0f} UZS) uchun iltimos:\n"
                        f"1. Ism-familiya\n2. Telefon (+998...)\n3. Manzil yuboring.")
            return (f"✨ **{p.name}**\n💵 {p.price:,.0f} {p.currency}\n📦 "
                    f"{'Mavjud' if p.in_stock else 'Tugagan'}\n📝 {p.description}\n\n"
                    f"Buyurtma berasizmi? Ism va telefon raqamingizni qoldiring!")
        if not products:
            return "Katalog hozircha bo'sh. Tez orada mahsulotlar qo'shiladi!"
        cat = "\n".join(f"• **{p.name}** — {p.price:,.0f} {p.currency}" for p in products[:8])
        return f"Bizdagi mahsulotlar:\n\n{cat}\n\nQaysi biri haqida batafsil bilmoqchisiz?"


ai_agent = AISalesAgent()
