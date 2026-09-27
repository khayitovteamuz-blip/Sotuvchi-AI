# Sotuvchi AI arxitekturasi

## Chegaralar

Tizim bitta deploy ichida uchta aniq qatlamdan iborat:

1. **Kirish kanallari** — biznes paneli, platforma paneli va Telegram.
2. **Biznes logikasi** — AI, katalog, buyurtma, billing, Inbox va bildirishnomalar.
3. **Infratuzilma** — PostgreSQL, S3 va tashqi AI/Telegram API'lari.

HTTP router faqat autentifikatsiya, validatsiya va javob formatiga javob beradi.
Biznes qarorlari `app/services`, tenant-scoped ma'lumot amallari `app/db/repo.py`
ichida turadi. Yangi kod bu chegarani buzmasligi kerak.

## Asosiy oqimlar

### Telegram savdosi

```text
Telegram -> webhook secret -> durable update claim -> bot guards
         -> conversation/message -> quota -> AI provider
         -> tool executor -> locked catalog/order transaction
         -> response/photo or human handoff
```

`(tenant_id, update_id)` Telegram update'ni bir marta ishlashga majbur qiladi.
Buyurtmadagi `source_update_id` retry qisman bajarilgan holatda ham ikkinchi order
yaratilishiga yo'l qo'ymaydi. Mahsulot qoldig'i order bilan bitta transactionda
`FOR UPDATE` ostida rezerv qilinadi.

### Pul oqimi

```text
tenant top-up request -> pending payment -> platform admin confirmation
                      -> locked payment + locked tenant -> balance ledger
                      -> plan purchase/renewal -> subscription period
```

Pul qiymatlari PostgreSQL `NUMERIC(18,2)`da saqlanadi. Har bir balans o'zgarishi
`payments` ledgerida iz qoldiradi. Platforma amallari audit jurnaliga yoziladi.

## Xavfsizlik invariantlari

- Har bir biznes qatori `tenant_id` bilan filtrlanadi.
- Platforma admin sessiyasi biznes sessiyasidan alohida.
- Cookie tokenining faqat SHA-256 hashi bazada saqlanadi.
- Parollar Argon2id bilan hashlanadi.
- Telegram tokenlari `ENCRYPTION_KEY` orqali shifrlanadi.
- Narx, qoldiq va order ID model matnidan emas, tool natijasidan olinadi.
- Upload turi filename bilan emas, fayl baytlari bilan aniqlanadi.
- Migratsiya yozuvchilari PostgreSQL advisory lock bilan serializatsiya qilinadi.

## Kengaytirish qoidasi

Instagram, WhatsApp yoki web widget qo'shilganda yangi kanal faqat kirish/chiqish
adapteri bo'lishi kerak. U `Conversation`, `AISalesAgent` va tool qatlamini qayta
yozmasligi kerak. Payme/Click ham billing ledgeriga adapter sifatida ulanadi;
balansni to'g'ridan-to'g'ri o'zgartirmaydi.
