"""Fon vazifasi: operator jim qolgan suhbatlarga raqam yuborish.

Bazasiz — repo va bot_service o'rniga soxta obyektlar qo'yiladi. Asosiy
talab: mijoz bitta raqamni ikki marta olmasligi (claim), va bitta suhbatdagi
xato qolganlarini to'xtatmasligi.
"""
import pytest

from app.services import contact_reminder as cr

ROW = {
    "id": "conv-1",
    "tenant_id": "t-1",
    "external_id": "555",
    "telegram_business_connection_id": None,
    "contact_phone": "+998 90 111 22 33",
    "ai_language": "uz",
}


class FakeTenant:
    telegram_bot_token = "tok"


@pytest.fixture
def stub(monkeypatch):
    state = {"claimed": set(), "sent": [], "stored": [], "rows": [dict(ROW)],
             "released": [], "send_ok": True}

    async def stranded(session, cutoff, limit=50):
        return state["rows"]

    async def claim(session, tenant_id, conv_id, at):
        if conv_id in state["claimed"]:
            return False
        state["claimed"].add(conv_id)
        return True

    async def get_conv(session, tenant_id, conv_id):
        return object()

    async def add_message(session, tenant_id, conv, sender, text, **kw):
        state["stored"].append((sender, text))

    async def release(session, tenant_id, conv_id):
        state["released"].append(conv_id)
        state["claimed"].discard(conv_id)

    async def send_message(token, chat_id, text, reply_markup=None,
                           parse_mode="Markdown", business_connection_id=None):
        state["sent"].append({"chat_id": chat_id, "text": text})
        return state["send_ok"]

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, model, pk):
            return FakeTenant()

    monkeypatch.setattr(cr.repo, "stranded_conversations", stranded)
    monkeypatch.setattr(cr.repo, "claim_contact_reminder", claim)
    monkeypatch.setattr(cr.repo, "release_contact_reminder", release)
    monkeypatch.setattr(cr.repo, "get_conversation", get_conv)
    monkeypatch.setattr(cr.repo, "add_message", add_message)
    monkeypatch.setattr(cr, "AsyncSessionLocal", FakeSession)

    from app.services import bot_service as bs
    monkeypatch.setattr(bs.bot_service, "send_message", send_message)
    return state


async def test_kutib_qolgan_suhbatga_raqam_yuboriladi(stub):
    yuborildi = await cr.contact_reminder.sweep()
    assert yuborildi == 1
    assert stub["sent"][0]["chat_id"] == "555"
    assert "+998 90 111 22 33" in stub["sent"][0]["text"]


async def test_yuborilgan_xabar_suhbatga_yoziladi(stub):
    # Inboxda mijoz ko'rgan narsaning aynan o'zi turishi kerak.
    await cr.contact_reminder.sweep()
    assert stub["stored"] and stub["stored"][0][0] == "assistant"


async def test_ikkinchi_aylanishda_takrorlanmaydi(stub):
    await cr.contact_reminder.sweep()
    yuborildi = await cr.contact_reminder.sweep()
    assert yuborildi == 0, "claim ikkinchi yuborishni to'xtatishi kerak"
    assert len(stub["sent"]) == 1


async def test_yuborilmasa_claim_qaytariladi(stub):
    # Tarmoq uzilsa, keyingi aylanishda qayta urinilsin — bitta xato tufayli
    # mijoz raqamdan butunlay mahrum bo'lmasin.
    stub["send_ok"] = False
    assert await cr.contact_reminder.sweep() == 0
    assert stub["released"] == ["conv-1"]

    stub["send_ok"] = True
    assert await cr.contact_reminder.sweep() == 1


async def test_raqam_bosh_bolsa_yuborilmaydi(stub):
    stub["rows"] = [dict(ROW, contact_phone="   ", id="conv-2")]
    assert await cr.contact_reminder.sweep() == 0
    assert stub["sent"] == []


async def test_bitta_suhbatdagi_xato_qolganini_toxtatmaydi(stub, monkeypatch):
    stub["rows"] = [dict(ROW, id="conv-a"), dict(ROW, id="conv-b", external_id="666")]

    async def yarim_ishlaydi(session, tenant_id, conv_id, at):
        if conv_id == "conv-a":
            raise RuntimeError("baza yiqildi")
        return True

    monkeypatch.setattr(cr.repo, "claim_contact_reminder", yarim_ishlaydi)
    yuborildi = await cr.contact_reminder.sweep()
    assert yuborildi == 1
    assert stub["sent"][0]["chat_id"] == "666"
