"""Operator jim qolganda aloqa raqami berilishi.

Bazasiz: contact_reminder_due sof funksiya — unga xabarlar ro'yxati va
hozirgi vaqt beriladi. Mijozni jim chatda unutib qo'ymaslik shu qoidaga
bog'liq, shuning uchun chegara holatlari ham shu yerda qulflangan.
"""
from datetime import datetime, timedelta, timezone

from app.services.ai_agent import CONTACT_REMINDER_MINUTES, contact_reminder_due

PHONE = "+998 90 123 45 67"
NOW = datetime(2026, 9, 27, 12, 0, tzinfo=timezone.utc)


class Msg:
    def __init__(self, sender, minutes_ago, text=""):
        self.sender = sender
        self.text = text
        self.created_at = NOW - timedelta(minutes=minutes_ago)


def test_uzoq_jimlikdan_keyin_raqam_beriladi():
    history = [Msg("user", 40), Msg("assistant", 35), Msg("user", 2)]
    assert contact_reminder_due(history, PHONE, NOW) is True


def test_yaqinda_javob_berilgan_bolsa_berilmaydi():
    history = [Msg("user", 10), Msg("operator", 3)]
    assert contact_reminder_due(history, PHONE, NOW) is False


def test_operator_javobi_hisoblagichni_nolga_tushiradi():
    # Eski AI javobi bor, lekin operator hozirgina yozgan — chat tirik.
    history = [Msg("assistant", 60), Msg("operator", 1)]
    assert contact_reminder_due(history, PHONE, NOW) is False


def test_raqam_yoq_bolsa_hech_narsa_qilinmaydi():
    history = [Msg("assistant", 90)]
    assert contact_reminder_due(history, None, NOW) is False
    assert contact_reminder_due(history, "  ", NOW) is False


def test_raqam_allaqachon_berilgan_bolsa_takrorlanmaydi():
    history = [
        Msg("assistant", 90),
        Msg("assistant", 60, f"📞 Tezroq javob kerak bo'lsa: {PHONE}"),
        Msg("user", 1),
    ]
    assert contact_reminder_due(history, PHONE, NOW) is False


def test_biz_hali_hech_narsa_yozmagan_bolsak_ham_beriladi():
    # Faqat mijoz xabarlari bor: masalan /start dan keyin darhol "Operator"
    # tugmasi bosilgan. Bunday mijoz ham kutmoqda, shuning uchun eng eski
    # xabardan hisoblanadi — aks holda u butunlay unutilib qolardi.
    history = [Msg("user", 90), Msg("user", 2)]
    assert contact_reminder_due(history, PHONE, NOW) is True


def test_yaqinda_boshlangan_suhbat_hali_kutmaydi():
    history = [Msg("user", 5), Msg("user", 1)]
    assert contact_reminder_due(history, PHONE, NOW) is False


def test_bosh_tarix():
    assert contact_reminder_due([], PHONE, NOW) is False


def test_chegaraning_ayni_ozida_beriladi():
    history = [Msg("assistant", CONTACT_REMINDER_MINUTES)]
    assert contact_reminder_due(history, PHONE, NOW) is True


def test_chegaradan_bir_daqiqa_oldin_berilmaydi():
    history = [Msg("assistant", CONTACT_REMINDER_MINUTES - 1)]
    assert contact_reminder_due(history, PHONE, NOW) is False


def test_chegarani_ozgartirish_mumkin():
    history = [Msg("assistant", 5)]
    assert contact_reminder_due(history, PHONE, NOW, after_minutes=3) is True
    assert contact_reminder_due(history, PHONE, NOW, after_minutes=30) is False
