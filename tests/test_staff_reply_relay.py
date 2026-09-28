"""Guruhdagi reply mijozga uzatilishi.

Bazasiz: repo va Telegram chaqiruvlari o'rniga soxta obyektlar. Bu yo'l
mijozga to'g'ridan-to'g'ri boradi, shuning uchun asosiy qoidalar shu yerda
qulflangan: begona reply uzatilmaydi, media file_id bilan ketadi, va har bir
uzatilgan javob suhbatga yoziladi (aks holda "operator jim" taymeri xodim
ishlayotgan suhbatga bostirib kirardi).
"""
import pytest

from app.services import bot_service as bs

ALERT = {"chat_id": "-100777", "message_id": "42"}


class FakeConv:
    id = "conv-1"
    external_id = "555"
    telegram_business_connection_id = None


@pytest.fixture
def stub(monkeypatch):
    state = {"sent": [], "stored": [], "released": [], "conv": FakeConv()}

    async def by_alert(session, tenant_id, chat_id, message_id):
        if {"chat_id": str(chat_id), "message_id": str(message_id)} == ALERT:
            return state["conv"]
        return None

    async def add_message(session, tenant_id, conv, sender, text, **kw):
        state["stored"].append((sender, text))

    async def release(session, tenant_id, conv_id):
        state["released"].append(conv_id)

    async def send_message(token, chat_id, text, reply_markup=None,
                           parse_mode="Markdown", business_connection_id=None):
        state["sent"].append({"kind": "text", "chat_id": chat_id, "body": text})
        return True

    async def send_photo(token, chat_id, photo, caption=None, business_connection_id=None):
        state["sent"].append({"kind": "photo", "chat_id": chat_id, "body": photo, "caption": caption})
        return True

    async def send_document(token, chat_id, file_id, caption=None, business_connection_id=None):
        state["sent"].append({"kind": "doc", "chat_id": chat_id, "body": file_id, "caption": caption})
        return True

    monkeypatch.setattr(bs.repo, "conversation_by_alert", by_alert)
    monkeypatch.setattr(bs.repo, "add_message", add_message)
    monkeypatch.setattr(bs.repo, "release_contact_reminder", release)
    monkeypatch.setattr(bs.bot_service, "send_message", send_message)
    monkeypatch.setattr(bs.bot_service, "send_photo", send_photo)
    monkeypatch.setattr(bs.bot_service, "send_document", send_document)
    return state


class FakeTenant:
    id = "t-1"


def _msg(**kw):
    base = {
        "chat": {"id": ALERT["chat_id"], "type": "group"},
        "from": {"id": 7, "first_name": "Aziza"},
        "reply_to_message": {"message_id": int(ALERT["message_id"])},
    }
    base.update(kw)
    return base


async def _relay(stub, msg, text=""):
    return await bs.bot_service._relay_staff_reply(
        None, FakeTenant(), "tok", msg, ALERT["chat_id"], text
    )


async def test_matn_mijozga_uzatiladi(stub):
    assert await _relay(stub, _msg(text="Ha, bor. Bugun yuboramiz."), "Ha, bor. Bugun yuboramiz.") is True
    mijozga = [s for s in stub["sent"] if s["chat_id"] == "555"]
    assert mijozga and mijozga[0]["body"] == "Ha, bor. Bugun yuboramiz."


async def test_rasm_file_id_bilan_ketadi(stub):
    msg = _msg(photo=[{"file_id": "small"}, {"file_id": "AgACBIG"}])
    await _relay(stub, msg, "Mana shu")
    rasm = [s for s in stub["sent"] if s["kind"] == "photo"]
    # Eng katta o'lcham olinadi va fayl qayta yuklanmaydi.
    assert rasm and rasm[0]["body"] == "AgACBIG"
    assert rasm[0]["caption"] == "Mana shu"


async def test_fayl_uzatiladi(stub):
    await _relay(stub, _msg(document={"file_id": "BQACdoc"}), "Narxlar")
    fayl = [s for s in stub["sent"] if s["kind"] == "doc"]
    assert fayl and fayl[0]["body"] == "BQACdoc"


async def test_begona_reply_uzatilmaydi(stub):
    # Boshqa xabarga qilingan reply — bu bizning ogohlantirishimiz emas.
    msg = _msg(reply_to_message={"message_id": 999}, text="salom")
    assert await _relay(stub, msg, "salom") is False
    assert stub["sent"] == []


async def test_oddiy_guruh_xabari_tegilmaydi(stub):
    msg = {"chat": {"id": ALERT["chat_id"], "type": "group"}, "from": {"id": 7}, "text": "tushlikka chiqdim"}
    assert await _relay(stub, msg, "tushlikka chiqdim") is False
    assert stub["sent"] == []


async def test_javob_suhbatga_yoziladi_va_taymer_toxtaydi(stub):
    await _relay(stub, _msg(text="javob"), "javob")
    assert stub["stored"] and stub["stored"][0][0] == "operator"
    assert stub["released"] == ["conv-1"]


async def test_xodimga_tasdiq_qaytadi(stub):
    await _relay(stub, _msg(text="javob"), "javob")
    guruhga = [s for s in stub["sent"] if s["chat_id"] == ALERT["chat_id"]]
    assert guruhga and "Aziza" in guruhga[0]["body"]


async def test_qollab_quvvatlanmaydigan_tur_aytiladi(stub):
    # Ovozli xabar: jim qolish o'rniga xodimga aniq aytiladi.
    await _relay(stub, _msg(voice={"file_id": "x"}), "")
    guruhga = [s for s in stub["sent"] if s["chat_id"] == ALERT["chat_id"]]
    assert guruhga and "uzatilmaydi" in guruhga[0]["body"]
    assert not [s for s in stub["sent"] if s["chat_id"] == "555"]
