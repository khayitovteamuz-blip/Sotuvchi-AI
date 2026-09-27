"""Operator topilmaganda mijozga aloqa raqami berilishi.

Bazasiz: ikkala funksiya ham sof — biri trace'ni o'qiydi, ikkinchisi matn
qaytaradi. Bu qoida mijoz javobsiz qolmasligini kafolatlaydi, shuning uchun
model xohishiga emas, shu testlarga bog'langan.
"""
from app.services.ai_agent import contact_fallback_text, handoff_left_unanswered

PHONE = "+998 90 123 45 67"


def _handoff(notified: bool) -> dict:
    return {"name": "handoff_to_human", "args": {}, "result": {"operator_notified": notified}}


# ─── handoff_left_unanswered ──────────────────────────────────────────────────
def test_uzatildi_lekin_hech_kimga_xabar_bormadi():
    assert handoff_left_unanswered([_handoff(False)]) is True


def test_uzatildi_va_operator_xabardor():
    assert handoff_left_unanswered([_handoff(True)]) is False


def test_uzatish_umuman_bolmagan_turn():
    trace = [{"name": "search_product", "args": {}, "result": {"found": 3}}]
    assert handoff_left_unanswered(trace) is False


def test_bosh_trace():
    assert handoff_left_unanswered([]) is False
    assert handoff_left_unanswered(None) is False


def test_operator_notified_maydoni_yoq_bolsa_xabarsiz_deb_hisoblanadi():
    # Eski yoki buzilgan natija: kafolat yo'q ekan, mijozga raqam berilgani
    # jim qolishdan xavfsizroq.
    trace = [{"name": "handoff_to_human", "args": {}, "result": {}}]
    assert handoff_left_unanswered(trace) is True


def test_bir_nechta_tool_orasidan_topadi():
    trace = [
        {"name": "search_product", "args": {}, "result": {"found": 1}},
        _handoff(False),
    ]
    assert handoff_left_unanswered(trace) is True


# ─── contact_fallback_text ────────────────────────────────────────────────────
def test_raqam_matnga_qoshiladi():
    out = contact_fallback_text(PHONE, "uz")
    assert PHONE in out
    assert out.startswith("\n\n")


def test_raqam_yoq_bolsa_bosh_qaytaradi():
    # Yo'q raqamni o'ylab topish yoki "bog'lanamiz" deb va'da berish
    # jim qolishdan yomonroq.
    assert contact_fallback_text(None, "uz") == ""
    assert contact_fallback_text("", "uz") == ""
    assert contact_fallback_text("   ", "uz") == ""


def test_til_boyicha_matn():
    assert "позвоните" in contact_fallback_text(PHONE, "ru")
    assert "Call us" in contact_fallback_text(PHONE, "en")
    assert "qo'ng'iroq" in contact_fallback_text(PHONE, "uz")


def test_notanish_til_ozbekchaga_tushadi():
    assert "qo'ng'iroq" in contact_fallback_text(PHONE, None)
    assert "qo'ng'iroq" in contact_fallback_text(PHONE, "de")


def test_raqam_atrofidagi_boshliq_belgilar_tozalanadi():
    assert contact_fallback_text(f"  {PHONE}  ", "uz").endswith(PHONE)
