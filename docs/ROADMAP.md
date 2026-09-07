# Product va engineering roadmap

## 0. Hozirgi holat

Yadro tayyor: multi-tenant auth, Telegram, katalog/import, AI tool-calling,
Inbox, order pipeline, billing, audit, RAG, Docker, backup va retention mavjud.

## 1. Production gate — deploydan oldin

- [x] Telegram webhook secret va durable idempotency
- [x] Atomik order/qoldiq va payment/balance amallari
- [x] Fixed-precision pul ustunlari
- [x] Tokenlarni bazada shifrlash
- [x] S3-compatible storage adapteri
- [x] Backup/restore va retention skriptlari
- [x] CI: lint va test
- [ ] Production `ENCRYPTION_KEY`, S3 va Sentry qiymatlarini hosting secretlariga kiritish
- [ ] Yangi migratsiyani staging bazada backup bilan sinash
- [ ] Telegram bot tokenini rotate qilish va biznes botlarini qayta ulash

## 2. Birinchi pullik mijozlar

- [ ] Email provider tanlash va transactional email adapteri
- [ ] Bir martalik, muddati cheklangan parol tiklash tokenlari
- [ ] Payme yoki Click merchant shartlari asosida payment adapteri
- [ ] Monitoring alertlari va haftalik restore testi
- [ ] Tenant onboarding funnel va AI/order conversion metrikalari

Bu ishlar credential, merchant shartnoma va yuboruvchi domenisiz “tayyor” deb
belgilanishi mumkin emas. Mock integratsiyani production integratsiya deb atamaslik kerak.

## 3. Growth

- [ ] Web widget kanal adapteri
- [ ] Instagram Messaging API adapteri
- [ ] WhatsApp Business adapteri
- [ ] Operator SLA, assignment va real-time Inbox
- [ ] RAG hujjatlarini qayta embedding qilish job'i

## 4. Scale triggerlari

Quyidagilar real o'lchov paydo bo'lganda qilinadi:

- webhook javobi platforma timeoutiga yaqinlashsa — DB-backed job worker;
- bitta Postgres instansiyasi yetmay qolsa — read model/cache;
- Inbox polling sezilarli yuk qilsa — SSE yoki WebSocket;
- tenant soni yuzlab bo'lsa — rate limitni Redis/Postgresga ko'chirish;
- `repo.py` domenlararo o'zgarishlarni qiyinlashtirsa — product/order/inbox repo'larga ajratish.

Mikroservisga erta bo'linmaydi. Hozirgi hajm uchun modular monolit tranzaksiya,
deploy va kuzatuv jihatidan sodda va to'g'ri tanlov.
