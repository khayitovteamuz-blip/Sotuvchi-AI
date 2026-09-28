"""Operator kutayotgan mijoz yozganda — guruhga nima boradi.

Bazasiz. Asosiy talablar: mijozning ovozli xabari guruhga haqiqiy ovoz
sifatida boradi (faqat "ovozli xabar yubordi" degan yozuv emas), va guruhga
tushgan har bir xabarga reply qilish o'sha mijozga yetib boradi — shuning
uchun izlar almashtirilmaydi, qo'shib boriladi.
"""
import pytest

from app.services import notify_service as ns


class FakeConv:
    def __init__(self, refs=None):
        self.external_id = "555"
        self.customer_name = "Aziz"
        self.handoff_alert_refs = refs or []


class FakeSession:
    async def commit(self):
        pass


# ─── remember_alert_refs ──────────────────────────────────────────────────────
def test_izlar_qoshiladi_almashtirilmaydi():
    conv = FakeConv([{"chat_id": "-1", "message_id": "1"}])
    ns.remember_alert_refs(conv, [{"chat_id": "-1", "message_id": "2"}])
    assert [r["message_id"] for r in conv.handoff_alert_refs] == ["1", "2"]


def test_izlar_cheksiz_osmaydi():
    conv = FakeConv()
    for i in range(ns.MAX_ALERT_REFS + 10):
        ns.remember_alert_refs(conv, [{"chat_id": "-1", "message_id": str(i)}])
    assert len(conv.handoff_alert_refs) == ns.MAX_ALERT_REFS
    # Eng yangilari qoladi — xodim odatda oxirgi xabarga javob beradi.
    assert conv.handoff_alert_refs[-1]["message_id"] == str(ns.MAX_ALERT_REFS + 9)


def test_bosh_izlar_holatni_buzmaydi():
    conv = FakeConv([{"chat_id": "-1", "message_id": "1"}])
    ns.remember_alert_refs(conv, [])
    assert len(conv.handoff_alert_refs) == 1


# ─── notify_customer_waiting ──────────────────────────────────────────────────
@pytest.fixture
def routing(monkeypatch):
    calls = {"text": [], "voice": []}

    def targets_for(cfg, event):
        return ["-100777"]

    async def send_tracked(session, tenant, cfg, event, text):
        calls["text"].append(text)
        return [{"chat_id": "-100777", "message_id": "10"}]

    async def send_voice_tracked(session, tenant, cfg, event, file_id, caption=None):
        calls["voice"].append(file_id)
        return [{"chat_id": "-100777", "message_id": "11"}]

    monkeypatch.setattr(ns.routing_service, "targets_for", targets_for)
    monkeypatch.setattr(ns.routing_service, "send_tracked", send_tracked)
    monkeypatch.setattr(ns.routing_service, "send_voice_tracked", send_voice_tracked)
    return calls


async def test_ovozli_xabar_guruhga_ovoz_sifatida_boradi(routing):
    conv = FakeConv()
    ok = await ns.notify_customer_waiting(
        FakeSession(), object(), object(), conv, "🎤 [ovozli xabar]", voice_file_id="AwACv"
    )
    assert ok is True
    assert routing["voice"] == ["AwACv"]
    # Ovozni o'rniga "ovozli xabar yubordi" degan matn yuborilmaydi.
    assert routing["text"] == []


async def test_ovozga_reply_qilsa_mijozga_boradi(routing):
    conv = FakeConv()
    await ns.notify_customer_waiting(
        FakeSession(), object(), object(), conv, "", voice_file_id="AwACv"
    )
    assert {"chat_id": "-100777", "message_id": "11"} in conv.handoff_alert_refs


async def test_matn_xabari_ham_kuzatiladi(routing):
    # Ilgari faqat birinchi ogohlantirish kuzatilardi — mijozning keyingi
    # xabariga reply qilsa, hech narsa bo'lmasdi.
    conv = FakeConv()
    await ns.notify_customer_waiting(FakeSession(), object(), object(), conv, "narxi qancha?")
    assert routing["text"] and "narxi qancha?" in routing["text"][0]
    assert {"chat_id": "-100777", "message_id": "10"} in conv.handoff_alert_refs


async def test_ega_oz_chatiga_ogohlantirilmaydi(routing, monkeypatch):
    # Egasining shaxsiy chati ham manzil, ham suhbat bo'lishi mumkin.
    monkeypatch.setattr(ns.routing_service, "targets_for", lambda cfg, e: ["555"])
    conv = FakeConv()
    assert await ns.notify_customer_waiting(FakeSession(), object(), object(), conv, "salom") is False
    assert routing["text"] == [] and routing["voice"] == []


# ─── _media_kind_label ────────────────────────────────────────────────────────
def test_yorliq_yuklab_olishga_bogliq_emas():
    # Yuklab olish yiqilsa ham Inboxda bo'sh pufakcha chiqmasin.
    from app.services.bot_service import _media_kind_label
    assert "ovozli" in _media_kind_label({"voice": {"file_id": "x"}})
    assert "rasm" in _media_kind_label({"photo": [{"file_id": "x"}]})
    assert "fayl" in _media_kind_label({"document": {"file_id": "x"}})
    assert _media_kind_label({"text": "salom"}) == ""
