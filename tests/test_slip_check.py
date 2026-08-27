"""To'lov chekini AI orqali tekshirish.

Bu tekshiruv hech qachon qaror qabul qilmaydi (slip_check.py'dagi izohga
qarang) — faqat tugmaning yonida turadigan matn tayyorlaydi, tasdiqlashni
odam bosadi. Shu sababli asosiy xavf: chek bo'lmagan rasmni chek deb
ko'rsatish yoki haqiqiy summa farqini sezmaslik. Tarmoqqa chiqmaydi —
Gemini chaqiruvi monkeypatch bilan almashtiriladi (google.genai.Client).
"""
import pytest

from app.core.config import settings
from app.services import slip_check


# ─── _num: chekdan o'qilgan summani raqamga aylantirish ───────────────────────
@pytest.mark.parametrize("raw, expected", [
    (3900000, 3900000.0),
    (3900000.5, 3900000.5),
    (0, 0.0),
    ("3900000", 3900000.0),
    ("3 900 000", 3900000.0),
    ("3,900,000", 3900000.0),
    ("15'200'000", 15200000.0),
    ("3900000.50", 3900000.5),
    ("3 900 000 so'm", 3900000.0),
    ("", None),
    (None, None),
    ("abc", None),
    ("3.900.000", None),   # ikkita nuqta — float() rad etadi, qo'lda solishtirishga qoladi
])
def test_num(raw, expected):
    assert slip_check._num(raw) == expected


# ─── verdict_line: tugma yonidagi bitta qator ──────────────────────────────────
def test_check_none_ai_javob_bermagan():
    assert "tekshirilmadi" in slip_check.verdict_line(None, 100000)


def test_chek_emas():
    check = {"is_receipt": False, "reason": "mahsulot surati"}
    line = slip_check.verdict_line(check, 100000)
    assert "DIQQAT" in line
    assert "mahsulot surati" in line


def test_chek_emas_sababsiz():
    check = {"is_receipt": False, "reason": None}
    assert "chekka o'xshamaydi" in slip_check.verdict_line(check, 100000)


def test_summa_oqilmadi():
    check = {"is_receipt": True, "amount": None}
    assert "summa o'qilmadi" in slip_check.verdict_line(check, 100000)


def test_summa_mos_kelmaydi():
    check = {"is_receipt": True, "amount": 100000}
    line = slip_check.verdict_line(check, 200000)
    assert "SUMMA MOS EMAS" in line
    assert "100,000" in line or "100000" in line


def test_summa_aniq_mos():
    check = {"is_receipt": True, "amount": 200000}
    line = slip_check.verdict_line(check, 200000)
    assert "✅" in line
    assert "mos" in line


def test_kichik_farq_tolerantlik_ichida():
    """0.5% farq — komissiya yoki yaxlitlash, ogohlantirish shart emas."""
    check = {"is_receipt": True, "amount": 201000}
    assert "✅" in slip_check.verdict_line(check, 200000)


def test_chegaradan_ortiq_farq_ogohlantiradi():
    """3% farq — tolerantlikdan (2%) oshadi."""
    check = {"is_receipt": True, "amount": 206000}
    assert "SUMMA MOS EMAS" in slip_check.verdict_line(check, 200000)


def test_sana_korsatiladi():
    check = {"is_receipt": True, "amount": 200000, "date": "12.08.2026"}
    assert "12.08.2026" in slip_check.verdict_line(check, 200000)


def test_buyurtma_summasi_nol_boodgi():
    """expected_total noma'lum (0) bo'lsa solishtirish o'tkazib yuboriladi —
    chek nima ko'rsatsa ham "mos" deb chiqadi, farq hisoblanmaydi."""
    check = {"is_receipt": True, "amount": 999999}
    assert "✅" in slip_check.verdict_line(check, 0)


# ─── inspect(): kalit yo'q yoki rasm yo'q bo'lsa hech narsaga chaqirmaydi ──────
async def test_kalit_yoq_bolsa_none(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "")
    assert await slip_check.inspect(b"rasm-baytlari") is None


async def test_rasm_yoq_bolsa_none(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")
    assert await slip_check.inspect(b"") is None


# ─── inspect(): Gemini javobini tahlil qilish (tarmoqsiz, soxta klient) ───────
class _FakeResponse:
    def __init__(self, text):
        self.text = text


class _FakeModels:
    def __init__(self, text):
        self._text = text

    def generate_content(self, *, model, contents):
        return _FakeResponse(self._text)


class _FakeClient:
    def __init__(self, text):
        self._text = text

    def __call__(self, *, api_key):
        return type("C", (), {"models": _FakeModels(self._text)})()


@pytest.fixture
def fake_key(monkeypatch):
    monkeypatch.setattr(settings, "GEMINI_API_KEY", "test-key")


def _mock_gemini(monkeypatch, response_text):
    from google import genai
    monkeypatch.setattr(genai, "Client", _FakeClient(response_text))


async def test_haqiqiy_chek_toliq_oqiladi(fake_key, monkeypatch):
    _mock_gemini(monkeypatch, """{
        "is_receipt": true, "amount": 3900000, "currency": "UZS",
        "date": "12.08.2026", "recipient": "8600 1234 5678 9012", "reason": null
    }""")
    result = await slip_check.inspect(b"rasm-baytlari")
    assert result == {
        "is_receipt": True, "amount": 3900000.0, "currency": "UZS",
        "date": "12.08.2026", "recipient": "8600 1234 5678 9012", "reason": None,
    }


async def test_kod_bloki_ichidagi_javob_ham_oqiladi(fake_key, monkeypatch):
    """Model ko'pincha ```json qatorlari bilan o'rab yuboradi — bular
    tashlab yuborilishi kerak."""
    _mock_gemini(monkeypatch, '```json\n{"is_receipt": true, "amount": 50000}\n```')
    result = await slip_check.inspect(b"rasm-baytlari")
    assert result["is_receipt"] is True
    assert result["amount"] == 50000.0


async def test_chek_emasligi_sababi_bilan_qaytadi(fake_key, monkeypatch):
    _mock_gemini(monkeypatch, '{"is_receipt": false, "amount": null, "reason": "mahsulot surati"}')
    result = await slip_check.inspect(b"rasm-baytlari")
    assert result["is_receipt"] is False
    assert result["reason"] == "mahsulot surati"


async def test_matn_koinishidagi_summa_ham_parse_qilinadi(fake_key, monkeypatch):
    """Model ba'zan summani formatlangan matn qilib yuboradi — _num shuni ushlaydi."""
    _mock_gemini(monkeypatch, '{"is_receipt": true, "amount": "3 900 000 so\'m"}')
    result = await slip_check.inspect(b"rasm-baytlari")
    assert result["amount"] == 3900000.0


async def test_buzuq_javob_none_qaytaradi(fake_key, monkeypatch):
    """AI JSON emas, oddiy matn qaytarsa — tekshiruv "ishlamadi" deb hisoblanadi,
    xato AI tugma yonidagi tasdiqni bloklamasligi kerak."""
    _mock_gemini(monkeypatch, "kechirasiz, bu rasmni tahlil qila olmayman")
    assert await slip_check.inspect(b"rasm-baytlari") is None
