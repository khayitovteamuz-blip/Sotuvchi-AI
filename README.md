# Sotuvchi AI

O'zbek tilida ishlaydigan AI sotuvchi: Telegram orqali mijoz bilan suhbatlashadi,
katalogdan mahsulot topadi, buyurtma rasmiylashtiradi va kerak bo'lganda operatorga
uzatadi. Har bir biznes o'z panelida katalogini, AI sozlamalarini va buyurtmalarini
boshqaradi; servis operatori esa `/boshqaruv` panelida barcha bizneslarni ko'radi.

- **Biznes paneli** — `/`
- **Platforma boshqaruvi** — `/boshqaruv`
- Texnologiya: FastAPI · PostgreSQL (pgvector) · Gemini · Telegram Bot API

---

## Hosting: nimaga qo'yish mumkin

Ilova doimiy ishlaydigan Python jarayoni. Unga kerak:

- Python 3.12 muhiti
- To'xtamaydigan protsess (Telegram polling va connection pool uchun)
- Tashqi Postgres (Supabase)

**Netlify, Vercel, GitHub Pages bu ilovani ishga tushira olmaydi** — ular statik
sayt va qisqa umrli serverless funksiyalar uchun. Netlify Functions faqat
JavaScript/TypeScript va Go ni qo'llab-quvvatlaydi; Python runtime yo'q. Sahifalar
esa serverda Jinja2 bilan render qilinadi, ya'ni "statik eksport" ham chiqmaydi.

Ishlaydigan variantlar — hammasi shu Dockerfile bilan:

| Platforma | Izoh |
|---|---|
| **Railway** | Eng sodda. Repo ulanadi, Dockerfile o'zi topiladi |
| **Render** | Web Service → Docker. Bepul tarifda uxlab qoladi |
| **Fly.io** | Foydalanuvchiga eng yaqin mintaqa tanlash mumkin |
| DigitalOcean App Platform / Koyeb | Xuddi shunday ishlaydi |

---

## Deploy

### 1. Supabase

Loyiha yarating va connection string'ni oling (Session pooler, port `5432`).
`pgvector` kengaytmasi kerak — migratsiya uni o'zi yoqadi.

### 2. Platformada muhit o'zgaruvchilari

Majburiy:

```bash
DATABASE_URL=postgresql+asyncpg://postgres.xxx:PAROL@aws-0-...pooler.supabase.com:5432/postgres
GEMINI_API_KEY=AIza...
PUBLIC_BASE_URL=https://sizning-domeningiz.uz
TELEGRAM_POLLING=false
DEBUG=False
```

Ixtiyoriy, lekin tavsiya etiladi:

```bash
AI_PRICE_INPUT_PER_1M=      # provayder narx sahifasidan, USD
AI_PRICE_OUTPUT_PER_1M=
USD_TO_UZS=                 # busiz xarajat faqat tokenda ko'rinadi
TIMEZONE_OFFSET_HOURS=5     # O'zbekiston, yozgi vaqt yo'q
WEB_CONCURRENCY=2           # worker soni
```

`PUBLIC_BASE_URL` ikki ish qiladi: cookie'ga `secure` bayrog'ini qo'yadi va
Telegram webhook manzilini yasaydi. HTTPS bilan yozilishi shart.

### 3. Deploy

Repo'ni platformaga ulang. Dockerfile o'zi topiladi va konteyner ichida:

1. `alembic upgrade head` — sxema yangilanadi
2. `uvicorn` ko'p worker bilan ishga tushadi

Migratsiyani qo'lda boshqarmoqchi bo'lsangiz `RUN_MIGRATIONS=false` qo'ying.

### 4. Domen

Platformaning domen bo'limida o'z domeningizni ulang, TLS avtomatik beriladi.
Keyin `PUBLIC_BASE_URL` ni o'sha domenga to'g'rilang va qayta deploy qiling.

### 5. Deploydan keyin — shart

**Har bir biznes Telegram botini panelidan qayta ulashi kerak.** Polling
rejimida webhook siri yaratilmagan; webhook rejimida bu sir bo'lmasa Telegram
so'rovlari 403 qaytadi. Panel → Integratsiyalar → botni qayta ulash.

Birinchi platforma admini faqat serverda yaratiladi:

```bash
python -m scripts.create_platform_admin
```

Keyingi adminlarni `/boshqaruv` → Adminlar bo'limidan qo'shasiz.

### Tekshirish

```bash
curl https://sizning-domeningiz.uz/api/health   # jarayon tirikmi
curl https://sizning-domeningiz.uz/api/ready    # bazaga ulanadimi
```

---

## Mahalliy ishga tushirish

```bash
uv venv --python 3.12 .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env          # DATABASE_URL va GEMINI_API_KEY ni to'ldiring
.venv/bin/python -m alembic upgrade head
./run.sh
```

`http://127.0.0.1:8080` ochiladi. `PUBLIC_BASE_URL` bo'sh bo'lsa Telegram
long-polling avtomatik yoqiladi — tunnel yoki deploy kerak emas.

Docker bilan sinash:

```bash
docker build -t sotuvchi-ai .
docker run --rm -p 8080:8080 --env-file .env sotuvchi-ai
```

---

## Tuzilma

```
app/
  api/         HTTP endpointlar (biznes paneli + platforma paneli alohida)
  core/        sozlama, autentifikatsiya, xavfsizlik, davrlar
  db/          modellar va ma'lumotga kirish qatlami
  services/    AI agent, Telegram bot, kvota, audit
alembic/       migratsiyalar
static/, templates/
scripts/       bir martalik va xizmat skriptlari
```

Tenant izolyatsiyasi: biznesga tegishli har bir qator `tenant_id` bilan
bog'langan va `app/db/repo.py` dagi barcha funksiyalar shu bo'yicha filtrlaydi.
Platforma paneli buni ataylab chetlab o'tadi, shuning uchun uning huquqi
`users` jadvalida emas — alohida `platform_admins` jadvalida.
