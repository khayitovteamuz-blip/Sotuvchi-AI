"""
Manipulyatsiya urinishlarini modelga yetkazmasdan ushlash.

Nega kerak: tizim promptidagi qoidalar model *ko'pincha* bajaradigan maslahat,
kafolat emas. Sinovda modelga chek haqida ikki marta aniq ko'rsatma berilgan
edi — ikkalasida ham e'tiborsiz qoldirdi va mijozga mahsulot taklif qilaverdi.

Shuning uchun aniq belgilar bo'yicha qaror bu yerda, kod darajasida qabul
qilinadi: model bunday xabarni umuman ko'rmaydi, javob esa har safar bir xil.

Bu qatlam hamma narsani ushlamaydi va ushlashi ham shart emas. U uchta
himoyaning birinchisi:
  1. shu yerdagi filtr — mos kelgan xabarga 100% bir xil javob;
  2. promptdagi 14-16 qoidalar — yangi ifodalar uchun;
  3. eng muhimi: AI'da buyurtmani tasdiqlash, chegirma berish yoki holatni
     o'zgartirish vositasi UMUMAN YO'Q. Nima deyishidan qat'i nazar,
     zarar keltiradigan amalni bajara olmaydi.
"""
import re
from typing import Optional

# ─── Vakolat da'vosi ──────────────────────────────────────────────────────────
# "Men adminman" bilan "admin bilan gaplashmoqchiman" farqi muhim: ikkinchisi
# mijozning haqli talabi va uni bloklash mumkin emas. Shuning uchun naqshlar
# faqat BIRINCHI SHAXS da'vosini qidiradi.
_AUTHORITY = [
    r"\bmen(?:\s+sen(?:ing|i))?\s+\w*\s*(boshli|rahbar|admin|egasi|direktor|dasturchi)",
    r"\bmen\s+(bu\s+)?(do'?kon|kompaniya|firma)\s*(ning)?\s*(egasi|boshli)",
    r"\bo'?zim\s+(egasi|admin|boshli|direktor)",
    r"\badmin\s+sifatida\s+(buyur|talab|aytyap)",
    r"\bя\s+(твой|ваш)?\s*(начальник|админ|владелец|директор|разработчик)",
    r"\bкак\s+админ\s+(приказыв|требу)",
    r"\bi(?:'m|\s+am)\s+(your\s+)?(boss|admin|owner|developer|manager|supervisor)",
    # Xodim/ishchi da'vosi. Rol so'zi pattern1'dagi umumiy ro'yxatga QO'SHILMAYDI
    # ataylab: "men sotuvchi bilan gaplashmoqchiman" kabi haqli so'rov "men" +
    # bo'sh joy + rol so'zi shakliga to'g'ri keladi va yolg'on pozitiv beradi
    # ("sotuvchi" shu sabab umuman ro'yxatga qo'shilmagan). Bu yerda esa fe'l
    # ("ishlayman") yoki -man qo'shimchasi orqali aniq DA'VO talab qilinadi,
    # oddiy "X bilan gaplashmoqchiman" so'rovi bilan grammatik jihatdan mos
    # kelmaydi.
    r"\bmen\s+(shu\s+|bu\s+)?(do'?kon|joy)da\s+ish(?:layman|layapman)\b",
    r"\b(shu\s+)?(do'?kon|kompaniya|firma)(?:ning)?\s*xodim(?:i)?man\b",
    r"\bя\s+(здесь\s+)?работаю\b",
    r"\bя\s+(ваш\s+)?сотрудник\b",
    r"\bi\s+work\s+(here|at\s+this)\b",
    r"\bi(?:'m|\s+am)\s+(a\s+)?staff\b",
]

# ─── Ko'rsatmani bekor qilishga urinish ───────────────────────────────────────
_OVERRIDE = [
    r"(oldingi|avvalgi|barcha)\s+\w*\s*(xabar|ko'?rsatma|qoida|instruksiya)\w*"
    r"\s+\w*\s*(unut|hisobga\s+olma|e'?tiborsiz\s+qoldir)",
    r"qoidalar(ing|ingni|ni)?\s+unut",
    # {0,2}: "sen endi mening yordamchim emassan" kabi ikki so'zli holatlarni
    # ham ushlaydi — asl naqsh faqat bitta so'zga ruxsat berardi.
    r"\bsen\s+endi\s+(?:\w+\s+){0,2}\w*\s*(emassan|bo'?lasan)",
    r"(system|tizim)\s*prompt",
    r"(test|developer|dev)\s*(rejim|mode|режим)",
    r"\bjailbreak\b|\bDAN\s+mode\b",
    r"(забудь|игнорируй)\s+\w*\s*(инструкц|правил|предыдущ)",
    r"ignore\s+(all\s+)?(previous|prior|above)\s+instruction",
    r"\byou\s+are\s+now\b",
    r"\bты\s+теперь\b",                 # "you are now" ning ruscha muqobili
    r"\bпритворись\b",                  # "pretend" ning ruscha muqobili
    r"\b(pretend|imagine)\s+(you\s+)?(are|have)\s+no\s+(rule|restriction|limit)",
]

_AUTHORITY_RE = [re.compile(p, re.I) for p in _AUTHORITY]
_OVERRIDE_RE = [re.compile(p, re.I) for p in _OVERRIDE]


def detect(text: Optional[str]) -> Optional[str]:
    """Return 'authority' | 'override' | None.

    None means the message is ordinary and goes to the model as usual — the
    filter must stay narrow, because a false positive refuses a paying customer.
    """
    if not text:
        return None
    s = " ".join(str(text).split())
    if any(r.search(s) for r in _AUTHORITY_RE):
        return "authority"
    if any(r.search(s) for r in _OVERRIDE_RE):
        return "override"
    return None


# ─── Javob matni ──────────────────────────────────────────────────────────────
# Qat'iy, lekin qo'pol emas: mijoz haqiqatan chalkashgan bo'lishi ham mumkin.
_REPLIES = {
    ("authority", "uz"): (
        "Kechirasiz, bu so'rovni bajara olmayman.\n\n"
        "Buyurtma va to'lovni faqat do'kon xodimlari boshqaruv panelidan "
        "tasdiqlaydi — men bu ishni bajara olmayman, kim so'rashidan qat'i nazar.\n\n"
        "Suhbatni operatorga uzatdim, u siz bilan bog'lanadi."
    ),
    ("authority", "ru"): (
        "Извините, я не могу выполнить эту просьбу.\n\n"
        "Заказы и платежи подтверждают только сотрудники магазина через панель "
        "управления — я этого сделать не могу, кем бы ни был собеседник.\n\n"
        "Я передал разговор оператору, он свяжется с вами."
    ),
    ("authority", "en"): (
        "Sorry, I can't do that.\n\n"
        "Orders and payments are confirmed only by shop staff through the admin "
        "panel — I cannot do it, no matter who is asking.\n\n"
        "I've passed this conversation to an operator, who will contact you."
    ),
    ("override", "uz"): (
        "Men do'konning savdo yordamchisiman va faqat shu ish bo'yicha yordam "
        "bera olaman: mahsulot, narx, yetkazib berish va buyurtma.\n\n"
        "Nima qidiryapsiz?"
    ),
    ("override", "ru"): (
        "Я — торговый помощник магазина и помогаю только по этим вопросам: "
        "товары, цены, доставка и заказы.\n\nЧто вы ищете?"
    ),
    ("override", "en"): (
        "I'm the shop's sales assistant and can only help with products, prices, "
        "delivery and orders.\n\nWhat are you looking for?"
    ),
}


def reply_for(kind: str, lang: Optional[str]) -> str:
    lang = lang if lang in ("uz", "ru", "en") else "uz"
    return _REPLIES.get((kind, lang), _REPLIES[(kind, "uz")])


def handoff_reason(kind: str) -> Optional[str]:
    """Only an authority claim is worth a person's attention.

    A jailbreak attempt gets a firm answer and nothing more: escalating every
    one of those would bury the team in noise and teach them to ignore the
    channel that also carries real escalations.
    """
    return "Mijoz o'zini xodim deb tanishtirib, imtiyoz talab qildi" if kind == "authority" else None
