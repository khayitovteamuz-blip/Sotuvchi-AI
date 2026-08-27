"""
Haqoratli xabarni aniqlash: birinchisiga ogohlantirish, ikkinchisiga blok.

Nega alohida modul: bu ishni modelga topshirib bo'lmaydi. Model kayfiyatga
qarab javob beradi — bir safar e'tiborsiz qoldiradi, bir safar o'zi ham
qo'polashadi, uchinchi safar uzr so'rab mahsulot taklif qilaveradi. Mijozni
bloklash esa qat'iy va oldindan aytib bo'ladigan qoida bo'lishi shart, aks
holda bir xil so'z bir mijozga kechiriladi, boshqasiga yo'q.

Filtrning asosiy xavfi — yolg'on ijobiy natija. Bloklangan mijoz — yo'qotilgan
pul, shuning uchun ro'yxat qisqa va aniq: faqat shubhasiz haqoratlar, so'z
chegarasi bilan. Shubhali holatda o'tkazib yuborish bloklashdan yaxshiroq.

Ishlatilishi `bot_service` da: `hits(text)` bo'lsa, `conv.abuse_count`
oshiriladi va shu qiymatga qarab ogohlantirish yoki blok yuboriladi.
"""
import re
from typing import Optional

# ─── O'zak ro'yxati ───────────────────────────────────────────────────────────
# Bular so'zning O'ZAGI: keyin kelgan qo'shimchalar (‑ing, ‑san, ‑lar) mos
# keladi, oldiga qo'shilgan harflar esa yo'q — "\b" boshida turibdi. Shuning
# uchun "sik" o'zagi "sikish" ni ushlaydi, lekin "psikolog" ni ushlamaydi.
# O'zbekcha qo'shimcha oladigan til: "ahmoq" bilan "ahmoqsan" bitta so'z.
# Qo'shimchalar ro'yxati aniq — ochiq `\w*` "eshak" ni "eshakmiya" (o'simlik)
# ga ham moslashtirib, o'simlik so'ragan mijozni ogohlantirib qo'yardi.
_SUF = r"(?:san|siz|sizlar|lar|larsan|ing|ingni|imiz|dir|misan)?"
_STEMS_UZ = [
    r"sik(?:ib|ish|aman|ay|di|kan|kansan|voraman)?",
    r"qottoq", r"qo'?toq", r"kot(?:oq|og')",
    r"am(?:ing|ingni|iga|gaqo'?y)",
    r"jala[bp]" + _SUF, r"dallo?l?a", r"onangni", r"onasini", r"padar",
    r"a[hx]moq" + _SUF, r"tentak" + _SUF, r"iflos" + _SUF,
    # "harom" o'zi haqorat emas — oziq-ovqat do'konida kundalik so'z
    # ("harom emas, halol"). Faqat shubhasiz shakllari qoladi.
    r"harom(?:zoda|xo'?r)" + _SUF,
    r"it(?:vachcha|dan\s+tarqagan)", r"eshak" + _SUF, r"nomard" + _SUF,
]
_STEMS_RU = [
    r"бля(?:дь|ди|ть)?", r"[пa]изд\w*", r"хуй\w*", r"хуе\w*", r"хуё\w*",
    r"еба\w*", r"ебё\w*", r"ебу\w*", r"ёб\w*", r"еби\w*",
    r"сук[аиу]\b", r"мраз\w*", r"гнид[аыу]", r"ублюдок", r"придурок",
    r"дебил\w*", r"идиот\w*", r"тварь", r"скотин[аы]", r"мудак",
    r"нахуй", r"похуй", r"пошёл\s+ты", r"пошел\s+ты",
]
_STEMS_EN = [
    r"fuck\w*", r"shit\w*", r"bitch\w*", r"bastard\w*", r"asshole\w*",
    r"cunt\w*", r"dickhead", r"motherfuck\w*", r"retard\w*", r"idiot\w*",
    r"stupid\s+bot", r"moron\w*",
]

_RE = [re.compile(r"\b" + p + r"\b", re.I | re.U)
       for p in _STEMS_UZ + _STEMS_RU + _STEMS_EN]

# Yulduzcha bilan yashirish ("s*ka", "f*ck") va harf takrori ("suuuka")
# filtrni chetlab o'tmasin.
_MASK = re.compile(r"[*@#$%^&_\-.]+")
_REPEAT = re.compile(r"(.)\1{2,}", re.U)


# Yulduzcha o'rniga qo'yib ko'riladigan harflar. Yashiruvchi odatda unlini
# olib tashlaydi ("s*ka", "f*ck"), shuning uchun ro'yxat unlilardan iborat.
_FILL = "aeiouаеиоуыя"
_MAX_MASKS = 2  # uchtadan ko'p yulduzcha bo'lsa tekshirish qimmatga tushadi


def _base(text: str) -> str:
    s = " ".join(str(text).split()).lower()
    return _REPEAT.sub(r"\1", s)   # suuuka -> suka


def _match(s: str) -> bool:
    return any(r.search(s) for r in _RE)


def hits(text: Optional[str]) -> bool:
    """Xabarda shubhasiz haqorat bormi."""
    if not text:
        return False
    s = _base(text)
    if _match(s):
        return True

    # Yashirilgan variant: "s*ka" -> suka, "f*ck" -> fuck. Yulduzchani o'chirib
    # tashlash yetarli emas — olib tashlangan harf o'zakni buzadi, shuning
    # uchun uning o'rniga unlilarni navbat bilan qo'yib ko'ramiz.
    masks = _MASK.findall(s)
    if not masks or len(masks) > _MAX_MASKS:
        return False
    parts = _MASK.split(s)
    if len(masks) == 1:
        return any(_match(parts[0] + c + parts[1]) for c in _FILL)
    return any(_match(parts[0] + a + parts[1] + b + parts[2])
               for a in _FILL for b in _FILL)


# ─── Javob matni ──────────────────────────────────────────────────────────────
_WARN = {
    "uz": (
        "Iltimos, muloyim gapiring. 🙏\n\n"
        "Bu — ogohlantirish. Haqoratli so'z yana takrorlansa, suhbat "
        "avtomatik yopiladi va sizga javob berilmaydi.\n\n"
        "Sizga qanday yordam bera olaman?"
    ),
    "ru": (
        "Пожалуйста, общайтесь вежливо. 🙏\n\n"
        "Это предупреждение. Если оскорбление повторится, разговор будет "
        "автоматически закрыт и ответов больше не будет.\n\n"
        "Чем я могу вам помочь?"
    ),
    "en": (
        "Please keep it civil. 🙏\n\n"
        "This is a warning. If the abuse is repeated, this chat will be closed "
        "automatically and you will not receive replies.\n\n"
        "How can I help you?"
    ),
}

_BLOCK = {
    "uz": (
        "Suhbat yopildi.\n\n"
        "Sizni bir marta ogohlantirgan edik. Haqoratli muloqot davom etgani "
        "uchun bu chatga endi javob berilmaydi.\n\n"
        "Agar bu xato bo'lsa deb hisoblasangiz, do'kon xodimlari bilan "
        "boshqa yo'l orqali bog'laning."
    ),
    "ru": (
        "Разговор закрыт.\n\n"
        "Мы вас предупреждали. Из-за продолжения оскорблений ответы в этом "
        "чате больше не отправляются.\n\n"
        "Если считаете это ошибкой, свяжитесь с сотрудниками магазина другим "
        "способом."
    ),
    "en": (
        "This chat is closed.\n\n"
        "You were warned once. Because the abuse continued, no further replies "
        "will be sent in this chat.\n\n"
        "If you believe this is a mistake, please contact the shop through "
        "another channel."
    ),
}


def warning_text(lang: Optional[str]) -> str:
    return _WARN.get(lang if lang in _WARN else "uz", _WARN["uz"])


def block_text(lang: Optional[str]) -> str:
    return _BLOCK.get(lang if lang in _BLOCK else "uz", _BLOCK["uz"])
