"""«Yozmoqda…» ko'rsatkichi.

Bazasiz va tarmoqsiz: sendChatAction o'rniga sanagich qo'yiladi. Bu bezak
bo'lgani uchun asosiy talab — u hech qachon javobni to'smasligi va o'zidan
keyin osilib qolgan vazifa qoldirmasligi.
"""
import asyncio

import pytest

from app.services.bot_service import bot_service


@pytest.fixture
def calls(monkeypatch):
    seen = []

    async def fake_action(token, chat_id, action="typing", business_connection_id=None):
        seen.append({"chat_id": chat_id, "action": action, "bc_id": business_connection_id})
        return True

    monkeypatch.setattr(bot_service, "send_chat_action", fake_action)
    monkeypatch.setattr("app.services.bot_service.TYPING_REFRESH_SECONDS", 0.01)
    return seen


async def test_blok_ichida_korsatkich_yuboriladi(calls):
    async with bot_service.typing("tok", "42"):
        await asyncio.sleep(0.05)
    assert calls, "hech bo'lmasa bitta 'typing' yuborilishi kerak"
    assert calls[0]["action"] == "typing"
    assert calls[0]["chat_id"] == "42"


async def test_uzoq_blokda_qayta_yangilanadi(calls):
    # Telegram ~5 soniyadan keyin o'chiradi, shuning uchun bitta yuborish kam.
    async with bot_service.typing("tok", "42"):
        await asyncio.sleep(0.06)
    assert len(calls) >= 2


async def test_blok_tugagach_toxtaydi(calls):
    async with bot_service.typing("tok", "42"):
        await asyncio.sleep(0.03)
    nechta = len(calls)
    await asyncio.sleep(0.05)
    assert len(calls) == nechta, "blokdan keyin yana yuborilmasligi kerak"


async def test_business_connection_id_uzatiladi(calls):
    async with bot_service.typing("tok", "42", "bc-123"):
        await asyncio.sleep(0.02)
    assert all(c["bc_id"] == "bc-123" for c in calls)


async def test_ichkaridagi_xato_yutilmaydi(calls):
    # Ko'rsatkich javobni "yeb qo'ymasligi" kerak: ichkaridagi xato yuqoriga
    # o'tadi, lekin osilib qolgan vazifa qolmaydi.
    with pytest.raises(ValueError):
        async with bot_service.typing("tok", "42"):
            raise ValueError("javob yozishda xato")
    nechta = len(calls)
    await asyncio.sleep(0.05)
    assert len(calls) == nechta


async def test_korsatkich_yiqilsa_ham_blok_ishlaydi(monkeypatch):
    # Telegram sendChatAction'ni rad etsa ham, mijoz javobini yo'qotmaymiz.
    async def broken(*a, **k):
        raise RuntimeError("Telegram yiqildi")

    monkeypatch.setattr(bot_service, "send_chat_action", broken)
    monkeypatch.setattr("app.services.bot_service.TYPING_REFRESH_SECONDS", 0.01)

    natija = None
    async with bot_service.typing("tok", "42"):
        natija = "javob tayyor"
        await asyncio.sleep(0.03)
    assert natija == "javob tayyor"
