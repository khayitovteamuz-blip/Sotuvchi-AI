# Sotuvchi AI — Claude Code uchun ish qoidalari

Men bilan **o'zbek tilida** gaplash. Kod, fayl, jadval va funksiya nomlari inglizcha qoladi.

## Loyiha nima

Telegram orqali o'zbek tilida savdo qiladigan AI sotuvchi. Kichik bizneslar (do'kon,
salon, klinika) uchun multi-tenant SaaS.

**Hozirgi maqsad: yangi funksiya emas — deploy va birinchi pullik mijoz.**
Kod yadrosi allaqachon bor. Endi eng muhimi uni ishonchli ishga tushirish.

## Stek

- Python 3.12, FastAPI, Jinja2 (server-side render), `static/` JS/CSS
- PostgreSQL (Supabase'da), **SQLAlchemy async + Alembic** — Supabase client kutubxonasi ishlatilmaydi
- AI: **Gemini** (`google-genai`) — asosiy provayder
- Telegram Bot API (webhook; lokal rejimda long-polling)
- S3-mos xotira (rasmlar), Sentry, Docker → Railway

## Arxitektura chegaralari (buzilmaydi)

- `app/api/*` — faqat autentifikatsiya, validatsiya, javob formati. Biznes logikasi yo'q.
- `app/services/*` — biznes qarorlari.
- `app/db/repo.py` — **bazaga tegadigan yagona joy.**
- Batafsil: `docs/ARCHITECTURE.md`.

## MVP chegarasi

Faqat shular ustida ishlanadi:

1. **Telegram bot** mijozga katalog bo'yicha o'zbekcha javob beradi.
2. **Buyurtma** qabul qiladi, qoldiqni rezerv qiladi, biznes egasiga xabar yuboradi.
3. **Operatorga uzatish:** bot tushunmasa yoki mijoz o'zi so'rasa — suhbat Inbox'dagi
   operatorga o'tadi. Operator javob bera olmasa yoki ulanmagan bo'lsa, mijozga
   biznesning **call-markaz / aloqa raqami** beriladi. (Raqam uchun sozlama va shu
   oqim to'liq ishlashini tekshir; yetishmasa — bu MVP ishi.)
4. **Biznes egasi paneli** — maksimal sodda, lekin xatosiz:
   katalog (Excel importi bilan), buyurtmalar, Inbox, botni ulash, aloqa raqami.
   Yangi tugma yoki bo'lim qo'shishdan oldin: "do'kon egasi busiz ishlay oladimi?"
   Ha bo'lsa — qo'shilmaydi. Bor narsaning xatosiz ishlashi yangi narsadan muhimroq.
5. **To'lov qo'lda:** karta o'tkazmasi → platforma admini tasdiqlaydi (allaqachon bor).
6. **Deploy:** Railway + Supabase + S3 + `ENCRYPTION_KEY` + Sentry (README'ga qara).

**Muzlatilgan — o'chirilmaydi, lekin tegilmaydi va kengaytirilmaydi:**
RAG, hisobotlar, support moduli, tariflar va murakkab billing, email,
Payme/Click, Instagram/WhatsApp/web widget kanallari.
Muzlatilgan qismda xato chiqsa va u MVP'ni buzsa — faqat minimal tuzatish.

**Har bir yangi ish shu savoldan o'tadi:**
"Bu birinchi pullik mijozga to'g'ridan-to'g'ri kerakmi?"
Javob "yo'q" bo'lsa — bajarma va menga ochiq ayt.
`docs/ROADMAP.md` eskirgan; ustuvorlikni shu bo'lim belgilaydi.

Ortiqcha narsa qo'shilmaydi: so'ralmagan refaktor, yangi kutubxona,
mikroservislarga bo'lish, "keyinchalik kerak bo'ladi" degan kod.

## Tenant izolyatsiyasi

- Biznesga tegishli har bir qator `tenant_id` bilan bog'langan.
- **Har bir ma'lumot amali faqat `app/db/repo.py` orqali va `tenant_id` filtri bilan.**
  Router yoki servisdan bazaga to'g'ridan-to'g'ri so'rov — taqiqlanadi.
- Postgres RLS ishlatilmaydi (ilova bitta umumiy foydalanuvchi bilan ulanadi).
  RLS qo'shishni taklif qilma.
- Platforma paneli izolyatsiyani ataylab chetlab o'tadi; uning huquqi alohida
  `platform_admins` jadvalida. Bu ikki sessiyani aralashtirma.

## Xavfsizlik invariantlari

- Narx, qoldiq va buyurtma ID **AI matnidan emas, faqat tool natijasidan** olinadi.
- Parollar Argon2id; cookie tokenining faqat SHA-256 hashi saqlanadi.
- Telegram bot tokenlari `ENCRYPTION_KEY` bilan shifrlanadi.
- Telegram webhook `secret_token` bilan tekshiriladi; update `(tenant_id, update_id)`
  bo'yicha bir marta ishlanadi.
- Upload turi fayl nomidan emas, baytlaridan aniqlanadi.
- Kalit va parollar faqat environment o'zgaruvchilarida. Kodga yozilmaydi.
- **`.env` faylini o'qima, ko'rsatma va o'zgartirma.** Kerakli nomlar `.env.example`da.
- **Production bazaga o'zing ulanma.**

## Bazadagi o'zgarishlar (migratsiyalar)

Migratsiya har deployda avtomatik ishlaydi — xato bo'lsa bazani buzadi.

- Har bir sxema o'zgarishi — yangi Alembic migratsiyasi. Eski migratsiyalar tahrirlanmaydi.
- Har bir migratsiyada ishlaydigan `downgrade()` bo'lishi shart.
- **Buzuvchi amallar faqat mening aniq ruxsatim bilan:** ustun/jadvalni o'chirish,
  nomini yoki tipini o'zgartirish. Avval nima yo'qolishini va qanday qaytarilishini tushuntir.

## AI sotuvchi xatti-harakati

`app/services/ai_agent.py`, `ai_tools.py`, `guard.py`, `profanity.py` yoki promptlarga
tegilganda:

- O'zgarishdan **oldin va keyin** benchmarkni ishga tushir va ballni ko'rsat:
  `.venv/bin/python -m eval.run_benchmark`
  **Ball tushsa — ish tayyor emas.**
- Yangi jailbreak yoki xato topilsa: avval `eval/benchmark.py`ga stsenariy qo'sh,
  keyin tuzat.
- Umumiy (platforma) va biznesga xos AI qoidalarining ikki qatlamini aralashtirma.

## Skillardan foydalanish

- Migratsiya, sxema, indeks, so'rov sifati → `supabase-postgres-best-practices`
  (RLS qismi bu loyihaga tegishli emas — yuqoriga qara)
- Sozlamalar, environment o'zgaruvchilari, kalitlar → `python-configuration`
- Webhook, endpoint, foydalanuvchi kiritgan matn, upload → `security-and-hardening`
- AI agent, prompt, guard → `agent-governance`

## Tekshirish buyruqlari

```bash
.venv/bin/ruff check app main.py tests eval scripts alembic
.venv/bin/python -m pytest
.venv/bin/python -m eval.run_benchmark
```

Testlar ataylab bazasiz ishlaydi. Yangi qoida (limit, pul, shifrlash, tekshiruv) qo'shilsa —
unga bazasiz test yoz.

## Git

- Har bir vazifa uchun `feature/<qisqa-nom>` branch. `main`ga to'g'ridan-to'g'ri commit yo'q.
- Commit xabari o'zbekcha, prefiks bilan: `feat:`, `fix:`, `refactor:`, `docs:`, `test:`.
- Commitdan oldin ruff va pytest o'tishi **shart**.
- **Push, merge va deploy — faqat mening ruxsatim bilan.**

## Men bilan ishlash uslubi

Men kod yozmayman — vibe coding orqali ishlayman. Shuning uchun:

- Oddiy so'zlar bilan tushuntir; texnik atamani ishlatsang, bir jumlada izohla.
- **Katta ishdan oldin** (3+ fayl, migratsiya, xavfsizlik yoki pul bilan bog'liq kod):
  3–5 bandlik reja ko'rsat va tasdiqlashimni kut. Kichik ishlarni so'ramay qil.
- **Ishdan keyin** 3 narsani ayt:
  1. nima o'zgardi;
  2. qanday tekshiraman (qaysi sahifa, qaysi tugma, botga nima yozish);
  3. qanday xavf yoki ochiq savol qoldi.
- Kod parchalarini javobga to'kma — so'rasam ko'rsatasan.
- Talabim arxitekturaga, xavfsizlikka yoki MVP chegarasiga zid bo'lsa — jim bajarma,
  avval ochiq ayt.
- Mock yoki soxta integratsiyani hech qachon "tayyor" dema.
