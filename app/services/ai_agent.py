"""
AI Sales Agent — tenant-scoped, Postgres-backed, tool-calling.

The model does not answer from the prompt alone: it calls tools (search_product,
check_stock, create_order, calc_delivery, handoff_to_human) that read and write
the tenant's real Postgres rows. Prices, stock and order ids therefore cannot be
hallucinated — that is the difference between this and a plain chatbot.

Falls back to a keyword sales engine when no API key is configured.
"""
import asyncio
import base64
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db import repo
from app.db.models import Conversation, Product, Tenant, TenantSettings
from app.models.schema import ChatResponse
from app.services import ai_models, ai_tools, quota_service

logger = logging.getLogger("ai_agent")

MAX_TOOL_ROUNDS = 5   # guard against a model looping on tools forever
MAX_RETRIES = 2       # retries on transient 429/503 from the API
MAX_RETRY_WAIT = 25.0 # seconds; longer than this we give up and use the fallback


def _new_usage() -> Dict[str, int]:
    return {"total": 0, "prompt": 0, "output": 0}


def _add_usage(usage: Dict[str, int], resp) -> None:
    """Accumulate one Gemini response's token counts.

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


def _bump(usage: Dict[str, int], prompt: int, output: int) -> None:
    usage["prompt"] += prompt
    usage["output"] += output
    usage["total"] += prompt + output


def _add_anthropic_usage(usage: Dict[str, int], resp) -> None:
    """Cached input is still input the shop pays for, so it is counted here too."""
    try:
        u = resp.usage
        prompt = ((u.input_tokens or 0)
                  + (getattr(u, "cache_read_input_tokens", 0) or 0)
                  + (getattr(u, "cache_creation_input_tokens", 0) or 0))
        _bump(usage, prompt, u.output_tokens or 0)
    except Exception:
        pass


def _add_openai_usage(usage: Dict[str, int], resp) -> None:
    try:
        u = resp.usage
        _bump(usage, u.prompt_tokens or 0, u.completion_tokens or 0)
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
    async def _quota_exhausted(self, session, tenant_id: str, conversation) -> ChatResponse:
        """The month's AI allowance is spent.

        The customer must not be left staring at silence, and the shop must not
        lose the sale, so the chat is escalated to a human and the handoff is
        stamped with a reason the owner can act on.
        """
        reply = ("Rahmat xabaringiz uchun 🙏 Hozir operatorimiz siz bilan "
                 "bog'lanadi va barcha savollaringizga javob beradi.")
        if conversation.status == "ai":
            conversation.status = "operator"
        if not conversation.handoff_reason:
            conversation.handoff_reason = "Oylik AI limiti tugadi — tarifni yangilash kerak"
        await repo.add_message(
            session, tenant_id, conversation, "assistant", reply,
            intent="quota_exhausted", model_name="quota-limit",
        )
        logger.warning(f"Tenant {tenant_id} is out of monthly AI messages — handed off")
        return ChatResponse(
            session_id=conversation.id,
            reply_text=reply,
            intent="quota_exhausted",
            recommended_products=[],
            order_draft=None,
            photos=[],
        )

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

        # Out of monthly allowance: hand the customer to a human rather than
        # answer with a smaller model or ignore the tariff. The shop still gets
        # the lead — it just costs a person instead of the AI.
        if not await quota_service.ai_allowed(session, tenant):
            return await self._quota_exhausted(session, tenant_id, conversation)

        t0 = time.monotonic()
        reply_text, model_used = "", None
        usage = _new_usage()
        tool_trace: List[Dict[str, Any]] = []

        # Which model actually answers this shop — decided by what the owner
        # picked in the panel, not by a hard-coded provider. None means no route
        # is open (missing key or SDK) and the keyword engine takes over.
        route = ai_models.resolve(cfg.ai_provider, cfg.model_name)

        if route:
            provider, model = route
            # A provider that can't read a voice note must not be handed one —
            # it would answer as though the customer had said nothing.
            readable = [m for m in (media or []) if ai_models.accepts_media(provider, m["mime_type"])]
            if media and not readable and not user_message:
                reply_text = self._unreadable_media_reply(media)
                model_used = "media-unsupported"
            else:
                runner = {
                    "gemini": self._run_gemini_with_tools,
                    "claude": self._run_anthropic_with_tools,
                    "openai": self._run_openai_with_tools,
                }[provider]
                reply_text, usage, tool_trace = await runner(
                    session, tenant_id, conversation, cfg, history,
                    user_message, user_name, readable, model,
                )
                model_used = model
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

        # "AI N marta javob topolmasa — operatorga uzat". Both panels have let
        # the owner set this for a long time; until now nothing read it, so the
        # promise was never kept and a customer could circle for ever.
        tool_trace = await self._auto_handoff_on_repeated_failure(
            session, tenant_id, conversation, cfg, tool_trace
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
        self, session, tenant_id, conversation, cfg, history,
        user_message, user_name, media=None, model=None,
    ) -> Tuple[str, Dict[str, int], List[Dict[str, Any]]]:
        try:
            from google.genai import types
        except Exception as e:
            logger.error(f"genai import failed: {e}")
            return ("", _new_usage(), [])

        client = self._client()
        if client is None:
            return ("", _new_usage(), [])
        model = model or cfg.model_name

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
            resp = await self._generate(client, model, contents, config)
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
            client, model, contents,
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

    # ─── Claude tool-calling loop ─────────────────────────────────────────────
    async def _run_anthropic_with_tools(
        self, session, tenant_id, conversation, cfg, history,
        user_message, user_name, media=None, model=None,
    ) -> Tuple[str, Dict[str, int], List[Dict[str, Any]]]:
        # Both the import and the constructor can fail (a missing package, an
        # empty key), and either one must degrade to the fallback engine rather
        # than take the customer's message down with it.
        try:
            import anthropic
            client = anthropic.AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)
        except Exception as e:
            logger.error(f"Claude client init failed: {e}")
            return ("", _new_usage(), [])

        model = model or "claude-opus-5"
        meta = ai_models.model_meta("claude", model) or {}
        system = self._system_instruction(cfg, conversation, user_name)

        messages = self._anthropic_history(history)
        blocks: List[Dict[str, Any]] = []
        for m in (media or []):
            blocks.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": m["mime_type"],
                    "data": base64.standard_b64encode(m["data"]).decode(),
                },
            })
        if user_message:
            blocks.append({"type": "text", "text": user_message})
        if not blocks:
            blocks.append({"type": "text", "text": "..."})
        messages.append({"role": "user", "content": blocks})

        # The 5-series takes adaptive thinking and rejects `temperature`;
        # Haiku 4.5 is the other way round. Sending the wrong one is a 400, not
        # a slightly worse answer — so each model carries its own flags.
        extra: Dict[str, Any] = {}
        if meta.get("adaptive"):
            extra["thinking"] = {"type": "adaptive"}
            # A sales reply is short and well specified; low effort keeps the
            # customer from waiting on reasoning they will never see.
            extra["output_config"] = {"effort": "low"}
        if meta.get("temperature"):
            extra["temperature"] = cfg.temperature

        tools = ai_tools.anthropic_tools()
        usage = _new_usage()
        trace: List[Dict[str, Any]] = []

        for _round in range(MAX_TOOL_ROUNDS):
            resp = await self._anthropic_call(client, model, system, messages, tools, extra)
            if resp is None:
                return ("", usage, trace)
            _add_anthropic_usage(usage, resp)

            # A refusal returns HTTP 200 with no answer in it; reading content[0]
            # here would hand the customer an empty bubble.
            if resp.stop_reason == "refusal":
                logger.warning("Claude declined the turn — using the fallback engine")
                return ("", usage, trace)

            calls = [b for b in resp.content if b.type == "tool_use"]
            if not calls:
                return (self._anthropic_text(resp), usage, trace)

            # Echo the model's own blocks back untouched: thinking blocks must
            # come back unchanged or the next request is rejected.
            messages.append({"role": "assistant", "content": resp.content})

            results = []
            for call in calls:
                args = dict(call.input or {})
                result = await ai_tools.execute_tool(
                    call.name, args, session, tenant_id, conversation
                )
                trace.append({"name": call.name, "args": args, "result": result})
                logger.info(f"[tool] {call.name}({args}) -> {str(result)[:160]}")
                results.append({
                    "type": "tool_result",
                    "tool_use_id": call.id,
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                })
            messages.append({"role": "user", "content": results})

        final = await self._anthropic_call(client, model, system, messages, None, extra)
        if final is None:
            return ("", usage, trace)
        _add_anthropic_usage(usage, final)
        return (self._anthropic_text(final), usage, trace)

    async def _anthropic_call(self, client, model, system, messages, tools, extra):
        for attempt in range(MAX_RETRIES + 1):
            try:
                kwargs: Dict[str, Any] = dict(
                    model=model, max_tokens=4096, system=system, messages=messages, **extra
                )
                if tools:
                    kwargs["tools"] = tools
                return await client.messages.create(**kwargs)
            except Exception as e:
                msg = str(e)
                low = msg.lower()
                transient = ("429" in msg or "529" in msg
                             or "rate_limit" in low or "overloaded" in low)
                if not transient or attempt == MAX_RETRIES:
                    logger.error(f"Claude API error ({'rate limit' if transient else 'fatal'}): {msg[:200]}")
                    return None
                wait = self._retry_delay(msg, attempt)
                if wait > MAX_RETRY_WAIT:
                    logger.error(f"Claude rate limited, retry delay {wait}s too long — using fallback")
                    return None
                logger.warning(f"Claude rate limited, retrying in {wait:.1f}s (attempt {attempt + 1})")
                await asyncio.sleep(wait)
        return None

    @staticmethod
    def _anthropic_text(resp) -> str:
        return "".join(b.text for b in resp.content if b.type == "text").strip()

    @staticmethod
    def _anthropic_history(history) -> List[Dict[str, Any]]:
        """Claude rejects an empty text block and a conversation that opens on
        the assistant, so a bot greeting sent before the customer spoke cannot
        be the first entry."""
        msgs: List[Dict[str, Any]] = []
        for m in history:
            text = (m.text or "").strip()
            if not text:
                continue
            role = "user" if m.sender == "user" else "assistant"
            if not msgs and role != "user":
                continue
            msgs.append({"role": role, "content": text})
        return msgs

    # ─── ChatGPT tool-calling loop ────────────────────────────────────────────
    async def _run_openai_with_tools(
        self, session, tenant_id, conversation, cfg, history,
        user_message, user_name, media=None, model=None,
    ) -> Tuple[str, Dict[str, int], List[Dict[str, Any]]]:
        try:
            from openai import AsyncOpenAI
            client = AsyncOpenAI(api_key=settings.OPENAI_API_KEY)
        except Exception as e:
            logger.error(f"OpenAI client init failed: {e}")
            return ("", _new_usage(), [])

        model = model or "gpt-5-mini"
        meta = ai_models.model_meta("openai", model) or {}

        messages: List[Dict[str, Any]] = [
            {"role": "system", "content": self._system_instruction(cfg, conversation, user_name)}
        ]
        for m in history:
            text = (m.text or "").strip()
            if text:
                messages.append({
                    "role": "user" if m.sender == "user" else "assistant",
                    "content": text,
                })

        parts: List[Dict[str, Any]] = []
        for m in (media or []):
            data = base64.standard_b64encode(m["data"]).decode()
            parts.append({"type": "image_url",
                          "image_url": {"url": f"data:{m['mime_type']};base64,{data}"}})
        if user_message:
            parts.append({"type": "text", "text": user_message})
        messages.append({"role": "user", "content": parts or (user_message or "...")})

        # The GPT-5 family only accepts the default temperature; the tenant's
        # slider is honoured on the older models that still read it.
        extra = {"temperature": cfg.temperature} if meta.get("temperature") else {}
        tools = ai_tools.openai_tools()
        usage = _new_usage()
        trace: List[Dict[str, Any]] = []

        for _round in range(MAX_TOOL_ROUNDS):
            resp = await self._openai_call(client, model, messages, tools, extra)
            if resp is None:
                return ("", usage, trace)
            _add_openai_usage(usage, resp)

            msg = resp.choices[0].message
            if not msg.tool_calls:
                return ((msg.content or "").strip(), usage, trace)

            messages.append(msg.model_dump(exclude_none=True))
            for call in msg.tool_calls:
                try:
                    args = json.loads(call.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                result = await ai_tools.execute_tool(
                    call.function.name, args, session, tenant_id, conversation
                )
                trace.append({"name": call.function.name, "args": args, "result": result})
                logger.info(f"[tool] {call.function.name}({args}) -> {str(result)[:160]}")
                messages.append({
                    "role": "tool",
                    "tool_call_id": call.id,
                    "content": json.dumps(result, ensure_ascii=False, default=str),
                })

        final = await self._openai_call(client, model, messages, None, extra)
        if final is None:
            return ("", usage, trace)
        _add_openai_usage(usage, final)
        return ((final.choices[0].message.content or "").strip(), usage, trace)

    async def _openai_call(self, client, model, messages, tools, extra):
        for attempt in range(MAX_RETRIES + 1):
            try:
                kwargs: Dict[str, Any] = dict(model=model, messages=messages, **extra)
                if tools:
                    kwargs["tools"] = tools
                return await client.chat.completions.create(**kwargs)
            except Exception as e:
                msg = str(e)
                low = msg.lower()
                transient = "429" in msg or "503" in msg or "rate limit" in low or "overloaded" in low
                if not transient or attempt == MAX_RETRIES:
                    logger.error(f"OpenAI API error ({'rate limit' if transient else 'fatal'}): {msg[:200]}")
                    return None
                wait = self._retry_delay(msg, attempt)
                if wait > MAX_RETRY_WAIT:
                    logger.error(f"OpenAI rate limited, retry delay {wait}s too long — using fallback")
                    return None
                logger.warning(f"OpenAI rate limited, retrying in {wait:.1f}s (attempt {attempt + 1})")
                await asyncio.sleep(wait)
        return None

    @staticmethod
    def _unreadable_media_reply(media) -> str:
        """The chosen model cannot open what the customer sent."""
        kind = "ovozli xabar" if (media or [{}])[0].get("mime_type", "").startswith("audio/") else "fayl"
        return (f"Kechirasiz, {kind}ni ocholmadim 😔 "
                "Iltimos, savolingizni matn bilan yozib yuboring.")

    # Phrases that mean "a human will take over" — if the model says one of
    # these it has made a promise to the customer that must be kept.
    _HANDOFF_PROMISE = re.compile(
        r"operator(imiz|ga|ni|lar)?\b.*\b(ula|bog'la|boglа|xabar|yuboraman|beradi|chaqir)"
        r"|operatorga\s+(ulay|ulab|uzat)"
        r"|mutaxassis(imiz)?\s+.*(bog'lan|javob)",
        re.IGNORECASE | re.DOTALL,
    )

    # Tools whose success means the turn produced something real, and the
    # fields that say "this call actually found data".
    _PRODUCTIVE_TOOLS = {"handoff_to_human", "create_order", "send_product_photo"}

    @staticmethod
    def _turn_was_useless(trace: List[Dict[str, Any]]) -> bool:
        """Did this turn fail to back its answer with any of the shop's data?

        A turn with no tool calls at all is not counted: a greeting or a thank-you
        needs no lookup, and counting those would escalate polite chatter.
        """
        if not trace:
            return False
        for t in trace:
            name, res = t["name"], (t.get("result") or {})
            if name in AISalesAgent._PRODUCTIVE_TOOLS:
                return False
            if res.get("found") not in (0, False, None):
                return False
            if name == "list_categories" and res.get("categories"):
                return False
            if name == "calc_delivery" and res.get("known"):
                return False
        return True

    async def _auto_handoff_on_repeated_failure(
        self, session, tenant_id, conversation, cfg, trace
    ):
        """Escalate after `auto_handoff_after` consecutive fruitless turns."""
        limit = cfg.auto_handoff_after or 0
        if limit <= 0 or conversation.status != "ai":
            return trace

        if not self._turn_was_useless(trace):
            conversation.fail_streak = 0
            return trace

        conversation.fail_streak = (conversation.fail_streak or 0) + 1
        if conversation.fail_streak < limit:
            return trace

        logger.info(
            f"Conversation {conversation.id}: {conversation.fail_streak} fruitless "
            f"turns in a row (limit {limit}) — handing to an operator"
        )
        reason = f"AI ketma-ket {conversation.fail_streak} marta javob topa olmadi"
        result = await ai_tools.execute_tool(
            "handoff_to_human", {"reason": reason}, session, tenant_id, conversation
        )
        conversation.fail_streak = 0
        return trace + [{"name": "handoff_to_human",
                         "args": {"reason": "auto-handoff-after-failures"},
                         "result": result}]

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
