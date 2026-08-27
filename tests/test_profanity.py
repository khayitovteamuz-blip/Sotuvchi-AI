"""Haqorat filtri: nimani ushlashi va — muhimrog'i — nimani ushlamasligi.

Yolg'on pozitiv bu yerda haqiqiy zarar: mijoz "halol go'sht kerak" deb yozsa
va ogohlantirish olsa, u qaytib kelmaydi. Shuning uchun toza xabarlar ro'yxati
haqoratlar ro'yxatidan uzunroq.
"""
import pytest

from app.services import profanity


@pytest.mark.parametrize("text", [
    "sen ahmoqsan",
    "ahmoqlar",
    "jalab",
    "jalabsan",
    "haromzoda",
    "onangni",
    "eshaksan",
    "iflos bot",
    "sikkansan",
    "AHMOQ",                 # katta harf
    "ты сука",
    "иди нахуй",
    "бляяяять",              # cho'zilgan harf
    "с*ка",                  # yulduzcha bilan yashirilgan
    "мудак",
    "дебил",
    "fuck you",
    "f*ck",
    "this is shit",
    "you stupid bot",
    "asshole",
])
def test_haqorat_ushlanadi(text):
    assert profanity.hits(text) is True


@pytest.mark.parametrize("text", [
    "salom, narxi qancha?",
    "assalomu alaykum",
    "yetkazib berasizmi?",
    "psikolog uchun kitob bormi?",       # 'sik' o'zagi so'z ichida
    "sikl generatori bormi",             # texnik atama
    "haromi emas halol go'sht kerak",    # oziq-ovqat do'konida kundalik so'z
    "halol go'sht bormi",
    "eshakmiya o'simligi bormi?",        # o'simlik nomi
    "tentakcha o'yinchoq bormi",
    "amir ismli mijozman",
    "сколько стоит?",
    "здравствуйте",
    "доставка есть?",
    "сукно есть в наличии?",             # 'сукно' — mato
    "how much is it?",
    "do you ship to Tashkent?",
    "",
    None,
])
def test_toza_xabar_otadi(text):
    assert profanity.hits(text) is False


def test_javob_matni_uch_tilda():
    for lang in ("uz", "ru", "en"):
        assert profanity.warning_text(lang)
        assert profanity.block_text(lang)
    # Noma'lum til o'zbekchaga tushadi, bo'sh javob emas.
    assert profanity.warning_text("de") == profanity.warning_text("uz")
    assert profanity.block_text(None) == profanity.block_text("uz")


def test_ogohlantirish_blokdan_farq_qiladi():
    """Ikki matn bir xil bo'lsa, mijoz ogohlantirilganini bilmaydi."""
    assert profanity.warning_text("uz") != profanity.block_text("uz")
