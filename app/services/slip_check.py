"""
To'lov chekini tekshirish.

Nega kerak: bot mijoz yuborgan har qanday rasmni chek deb qabul qilardi va
jamoaga "to'lov keldi" degan xabar borardi. Mahsulot surati, skrinshot yoki
umuman boshqa rasm ham chek sifatida o'tib ketardi — jamoa esa guruhda faqat
rasmni ko'rib "Tasdiqlash" tugmasini bosardi.

Bu yerdagi tekshiruv **qaror qabul qilmaydi**. U faqat chekning yonига AI
xulosasini qo'yadi, shunda tugmani bosayotgan odam nimani tasdiqlayotganini
biladi. Tasdiqlash baribir odam ishi bo'lib qoladi.
"""
import json
import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger("slip_check")

# Rasm chek ekanini va undagi summani aniqlaydigan so'rov. Ataylab qisqa:
# bu tasniflash vazifasi, suhbat emas.
PROMPT = """Bu rasm bank to'lov cheki (kvitansiya, screenshot yoki qog'oz chek)mi?

Faqat JSON qaytar, boshqa hech narsa yozma:
{
  "is_receipt": true/false,
  "amount": <raqam yoki null>,
  "currency": "<UZS/USD yoki null>",
  "date": "<matn yoki null>",
  "recipient": "<qabul qiluvchi karta/ism yoki null>",
  "reason": "<agar chek bo'lmasa, rasmda nima borligi - 4-6 so'z>"
}

Muhim: mahsulot surati, reklama rasmi, skrinshot yoki hujjat chek EMAS.
Summani raqam sifatida ber (masalan 3900000, "3 900 000 so'm" emas)."""


def _num(v: Any) -> Optional[float]:
    if isinstance(v, (int, float)):
        return float(v)
    if not v:
        return None
    s = re.sub(r"[^\d.]", "", str(v))
    try:
        return float(s) if s else None
    except ValueError:
        return None


async def inspect(image_bytes: bytes, mime_type: str = "image/jpeg") -> Optional[Dict[str, Any]]:
    """Ask the model what the image is. None when the check could not run."""
    from app.core.config import settings
    if not settings.GEMINI_API_KEY or not image_bytes:
        return None

    try:
        import asyncio
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        resp = await asyncio.to_thread(
            client.models.generate_content,
            model=settings.SLIP_CHECK_MODEL,
            contents=[
                types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                PROMPT,
            ],
        )
        text = re.sub(r"^```(?:json)?|```$", "", (resp.text or "").strip(), flags=re.M).strip()
        raw = json.loads(text)
    except Exception as e:                     # noqa: BLE001 - a failed check must not block the sale
        logger.info("Chek tekshiruvi ishlamadi: %s", e)
        return None

    return {
        "is_receipt": bool(raw.get("is_receipt")),
        "amount": _num(raw.get("amount")),
        "currency": raw.get("currency") or None,
        "date": raw.get("date") or None,
        "recipient": raw.get("recipient") or None,
        "reason": (raw.get("reason") or "").strip() or None,
    }


# Summa farqi shu foizdan oshsa, ogohlantiramiz. Nol emas: chek komissiya
# bilan yoki yaxlitlangan bo'lishi mumkin.
AMOUNT_TOLERANCE = 0.02


def verdict_line(check: Optional[Dict[str, Any]], expected_total: float) -> str:
    """One line for the team, above the confirm button."""
    if check is None:
        return "🔍 _Chek tekshirilmadi (AI javob bermadi) — o'zingiz ko'ring._"

    if not check["is_receipt"]:
        what = check.get("reason") or "chekka o'xshamaydi"
        return f"🚫 *DIQQAT: bu chek emas* — {what}.\nTasdiqlashdan oldin mijozdan haqiqiy chek so'rang."

    amount = check.get("amount")
    if amount is None:
        return "⚠️ Chekka o'xshaydi, lekin *summa o'qilmadi* — qo'lda solishtiring."

    diff = abs(amount - expected_total)
    if expected_total > 0 and diff / expected_total > AMOUNT_TOLERANCE:
        return (f"⚠️ *SUMMA MOS EMAS*\n"
                f"Chekda: {amount:,.0f} · Buyurtma: {expected_total:,.0f}")

    extra = f" · {check['date']}" if check.get("date") else ""
    return f"✅ Chek o'qildi: {amount:,.0f} — summa mos{extra}"
