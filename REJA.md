# Sotuvchi AI — funksiyalar holati

Bu ro'yxat 2026-08-21 dagi **haqiqiy kod tekshiruvidan** olingan: endpointlar,
servislar, baza jadvallari va tirik ulanishlar sanab chiqilgan. Taxmin yo'q.

Belgilar: **✅ ishlaydi** · **🟡 kodi bor, ulanmagan** · **⬜ faqat interfeys** · **❌ yo'q**

---

## 1. Poydevor — ✅ tayyor

| Narsa | Holat |
|---|---|
| Ko'p ijarachi (multi-tenant) | ✅ 4 tenant, har birining ma'lumoti ajratilgan |
| Ro'yxatdan o'tish / kirish | ✅ `POST /register`, `/login`, `/logout` |
| Sessiya va urinishlar nazorati | ✅ `user_sessions`, `login_attempts` jadvallari |
| Rollar (egasi / operator) | ✅ xodimlar qo'shish, tahrirlash, o'chirish |
| Maxfiy ma'lumot shifrlash | ✅ `ENCRYPTION_KEY`, Telegram tokeni bazada shifrlangan |
| Audit jurnali | ✅ `platform_audit_log` |
| Testlar | ✅ 7 ta fayl: billing, crypto, customers, quota, routing, storage |
| CI | ✅ `.github/workflows/ci.yml` |
| Docker | ✅ `Dockerfile`, `docker-entrypoint.sh` |

---

## 2. AI sotuvchi — ✅ yadro tayyor

AI sakkizta vositani o'zi chaqira oladi (`app/services/ai_tools.py`):

| Vosita | Nima qiladi |
|---|---|
| `search_product` | katalogdan mahsulot qidiradi |
| `check_stock` | ombor qoldig'ini tekshiradi |
| `calc_delivery` | yetkazish narxini hisoblaydi |
| `create_order` | buyurtma rasmiylashtiradi |
| `send_product_photo` | mahsulot rasmini yuboradi |
| `list_categories` | kategoriyalarni sanaydi |
| `search_knowledge` | bilimlar bazasidan javob qidiradi |
| `handoff_to_human` | operatorga uzatadi |

- **Model:** Gemini, kalit amal qiladi, 4 model tanlanadi (panelda)
- **Ijodkorlik (temperature):** panelda sozlanadi
- **Bilimlar bazasi:** yetkazish, to'lov, kafolat, qaytarish, ish vaqti, savol-javob
- **RAG uchun jadvallar:** `kb_documents`, `kb_chunks` — **jadval bor, lekin
  hujjat yuklash interfeysi yo'q** (2-bosqichga)

---

## 3. Kanallar

| Kanal | Holat | Izoh |
|---|---|---|
| **Telegram** | ✅ ishlaydi | `@sotuvchi_ai_robot`, `getMe` javob beryapti |
| Telegram — webhook rejimi | 🟡 kodi bor | hozir long-polling; hostingga chiqqanda webhookka o'tish kerak |
| **Instagram** | ⬜ faqat interfeys | backendda bitta ham endpoint yo'q |
| **Web widget** | ⬜ faqat interfeys | sayt uchun chat oynasi |
| WhatsApp | ❌ yo'q | rejada ham yo'q |

---

## 4. Katalog va buyurtma — ✅ tayyor

| Narsa | Holat |
|---|---|
| Mahsulot qo'shish / tahrirlash / o'chirish | ✅ |
| Kategoriyalar | ✅ qo'lda + **AI bilan avtomatik ajratish** |
| Excel'dan yuklash | ✅ **har qanday shakldagi jadval** (pastga qarang) |
| Excel'ga chiqarish | ✅ `.xlsx`, importer o'qiydigan shaklda |
| Rasm saqlash | ✅ `storage_service`, `static/uploads/` |
| Buyurtmalar + bosqichlar | ✅ Yangi → Tasdiqlandi → Yo'lda → Yetkazildi |
| Buyurtma tafsiloti paneli | ✅ mahsulotlar, manzil, jami, bosqich chizig'i |
| Mijozlar bazasi | ✅ `customers`, `customer_identities` |

---

## 5. Inbox va operator — ✅ tayyor

- Suhbatlar ro'yxati, qidiruv, holat bo'yicha saralash
- Operator javob berishi, AI'ga qaytarish, yopish, o'chirish
- `handoff_to_human` — AI o'zi operatorga uzatadi
- Bildirishnoma marshruti: `notify_channels` (qaysi xabar qayerga boradi)
- Xabar tomonlari: mijoz chapda (avatar bilan), AI va operator o'ngda
- **Haqorat nazorati:** birinchi so'kinishga ogohlantirish, ikkinchisiga blok.
  Bloklangan suhbatga bot umuman javob bermaydi (`/start` ga ham). Jamoaga
  xabar boradi, operator paneldan blokni bekor qila oladi.
  Filtr `app/services/profanity.py` — uch til, yulduzcha bilan yashirishni
  ham ushlaydi, oziq-ovqat do'koni uchun "harom" kabi kundalik so'zlarni esa
  ushlamaydi (`tests/test_profanity.py`).

---

## 6. Pul — ✅ ishlaydi, lekin qo'lda

| Narsa | Holat |
|---|---|
| Balans, tariflar, obuna | ✅ `plans`, `payments` jadvallari |
| Avtomatik yangilash | ✅ balansdan yechiladi |
| Limitlar (kvota) | ✅ mahsulot / AI xabar / operator |
| Muddat tugashi, freeze, grace | ✅ |
| **To'lovni qabul qilish** | ⬜ **Payme/Click ulanmagan** |
| To'lovni tasdiqlash | 🟡 faqat **qo'lda** — operator panelidan |

> Hozirgi oqim: mijoz pul o'tkazadi → panelda "Hisobni to'ldirish" bosib summa
> yozadi → siz `/boshqaruv` dan tasdiqlaysiz. Avtomatik emas.

---

## 7. Operator paneli `/boshqaruv` — ✅ tayyor

Tenantlar, adminlar, to'lovlar, tariflar, saqlash hajmi, statistika seriyalari,
CSV eksport, audit jurnali. Alohida autentifikatsiya (`platform_sessions`).

---

## 8. Integratsiyalar

| Narsa | Holat |
|---|---|
| **Google Sheets / CRM** | 🟡 `sheets_service.py` **bor**, lekin sozlanmagan |

Ishga tushirish uchun ikkitasi kerak:
1. `GOOGLE_SHEETS_SPREADSHEET_ID` — `.env` da bo'sh
2. `service_account.json` — **fayl umuman yo'q**

---

## 9. Umuman yo'q — lekin sotish uchun kerak

| Narsa | Nega kerak | Og'irlik |
|---|---|---|
| **Parolni tiklash** | mijoz parolni unutsa, qo'ldan yordam berish kerak | kichik |
| **Email yuborish** | tasdiqlash, hisob-faktura, ogohlantirish — SMTP umuman yo'q | o'rta |
| **Payme/Click** | to'lovni qo'lda tasdiqlash 10 mijozdan keyin ishlamay qoladi | katta |
| **Baza zaxirasi (avtomatik)** | `backups/` papkasi bor, lekin kod yo'q | o'rta |
| **Hisob-faktura / chek** | biznes mijozlar so'raydi | o'rta |
| **RAG hujjat yuklash** | jadvallar tayyor, interfeys yo'q | o'rta |
| **Telegram webhook** | hostingda polling ishlamaydi | **hosting oldidan shart** |

---

## 10. Tavsiya etilgan tartib

### Hostingga chiqishdan oldin — shart

1. **Telegram webhook** — long-polling faqat localhostda ishlaydi
2. **Parolni tiklash** — birinchi mijoz parolni unutishi aniq
3. **Baza zaxirasi** — kunlik avtomatik nusxa
4. `DEBUG=false`, `ENCRYPTION_KEY` ni prod uchun alohida yasash

### Birinchi mijozlargacha

5. **Payme/Click** — qo'lda tasdiqlash 5-10 mijozgacha chidaydi, keyin yo'q
6. **Email** — parol tiklash ham, tasdiqlash ham shunga bog'liq
7. **Excel eksport** — arzon, mijoz tez-tez so'raydi

### Keyinroq

8. RAG hujjat yuklash (jadvallar tayyor)
9. Instagram
10. Web widget

---

## 11. Excel import — nima qila oladi

- **Sarlavhani o'zi topadi** — fayl "PRAYS LIST 2026" bilan boshlansa ham
- **Uch til, ikki alifbo** — `Наименование` · `НОМИ` · `Product Name` · `Товар`
- **Ustun tartibi ahamiyatsiz**
- **Alias jadvalida yo'q sarlavhalarni AI tanidi** — `Что продаём` → nomi,
  `Сколько стоит за штуку` → narx (sinovdan o'tgan)
- **Narx formatlari:** `15 200 000` · `15,200,000` · `15.200.000` · `15'200'000` ·
  `1.5 mln` · `250 ming` · `3 млн` · `15 200 000 so'm`
- **Fayl ichidagi rasmlar** platformaga ko'chiriladi (Pillow shart —
  `requirements.txt` da)
- **Bir hujayrada bir nechta rasm havolasi** (vergul/nuqtali vergul bilan)
- Oldindan ko'rish: qaysi ustun qaysi maydonga tushgani ko'rsatiladi

---

## 12. Tezlik — nima o'lchandi

Panel sekin ishlashining asosiy sababi kodda emas, **masofada**:

| O'lchov | Natija |
|---|---|
| Bazagacha bitta borish-kelish | **~90 ms** (`select 1` ham shuncha) |
| Baza joylashuvi | Supabase `eu-central-1` — **Frankfurt** |
| Har bir endpoint qiladigan so'rov | 1-4 ta (N+1 muammosi **yo'q**) |

Ya'ni SQL tez, tarmoq sekin. Har bir so'rov Toshkent–Frankfurt masofasini
bosib o'tadi.

**Bajarilgan tuzatishlar:**

1. `pool_pre_ping` o'chirildi (`app/db/base.py`) — u har bir so'rov oldidan
   qo'shimcha "select 1" yuborardi. O'lchov: sessiya 565 ms → 273 ms.
   O'rniga `pool_recycle` 1800 → 300 soniya.
2. Katalog ikkita so'rovni endi birga yuboradi (`Promise.all`), ketma-ket emas.

Natija (haqiqiy panel o'lchovi):

| Endpoint | Oldin | Keyin |
|---|---|---|
| `/api/admin/categories` | 1000 ms | **557 ms** |
| `/api/admin/products` | 830 ms | **654 ms** |
| `/api/admin/orders` | 1019 ms | **761 ms** |
| `/api/inbox/conversations` | 829 ms | **747 ms** |

**Qolgan vaqt masofadan.** Uni kod bilan olib bo'lmaydi — faqat dasturni
baza bilan bir mintaqaga qo'yish bilan. Hosting Frankfurtda bo'lsa
(Railway EU), borish-kelish ~90 ms dan ~1-2 ms ga tushadi va panel bir necha
o'n barobar tezlashadi. Hozirgi sekinlik asosan **localhost'da ishlashning
oqibati**, hostingda o'z-o'zidan yo'qoladi.

---

## 13. Dashboard grafigi — ✅ haqiqiy ma'lumotga ulandi

Ilgari grafik `CHART_DATA` dagi qo'lda yozilgan raqamlarni chizardi
(`Yan…Iyun`, "Mar" yoritilgan) — chiroyli, lekin hech narsani anglatmaydigan
va haqiqiy ko'rsatkichdek ko'rinadigan.

Endi `GET /api/admin/analytics/series?span=oy|yil` haqiqiy ma'lumot beradi
(`repo.activity_series`):

- **Oy** — shu oyning kunlari, 1-kundan bugungacha
- **Yil** — shu yilning oylari, yanvardan shu oygacha
- **Fokus — bugungi kun** (yillik ko'rinishda shu oy), eng baland ustun emas:
  do'kon egasi grafikka "bugun qanday ketyapti?" deb qaraydi
- Har bir ustunda: suhbat soni va buyurtma soni (kursor ustiga borganda)
- Bo'sh kunlar ham ko'rsatiladi (`generate_series`) — uzilishni yashirmaslik uchun
- Umuman faoliyat bo'lmasa, bo'sh tayoqchalar emas, izoh chiqadi
- **Vaqt mintaqasi:** ustunlar `TIMEZONE_OFFSET_HOURS` (UTC+5) bilan siljitib
  kesiladi. Bu shart edi — aks holda mahalliy 00:00-05:00 oralig'idagi har bir
  suhbat oldingi kunga yozilar, soatlik ko'rinishda esa 15:00 dagi buyurtma
  10:00 da ko'rinardi.

Faoliyat yo'q oy/kun nol bo'lib turadi — bu haqiqat, va uni yashirish
o'sishni haqiqatdagidan tekisroq ko'rsatardi.

---

## 14. Tozalangan ma'lumot

`ORD-431F940E` o'chirildi — ikkita server bir vaqtda ishlagan paytda paydo
bo'lgan takroriy buyurtma (`ORD-5773F36B` bilan 2 soniya farq, bir xil mijoz,
summa va suhbat). Asli qaysi biri ekani aniq edi: `ORD-5773F36B` da tasdiq,
tasdiqlagan odam ismi va chek rasmi bor, takroriysida esa yo'q.

Zaxira: `backups/ORD-431F940E-takroriy.json`.
Natija: jami daromad 55 317 776 → 53 458 888 so'm.

---

## 15. Ikonkalar — Lucide

Material Symbols shrifti Lucide ikonkalariga almashtirildi (43 ta ikonka,
63 ta ishlatilish joyi).

**Qanday qilingan:** SVG'lar CSS ichiga `mask-image` sifatida joylashtirilgan,
`data:` URI bilan. Tashqi so'rov yo'q — CSP tashqi manbalarni to'sadi, shriftda
ham shu muammo bo'lgan edi.

**Nega JS ishlatilmadi:** ikonkalar sof CSS. Panel DOM'ni ko'p joyda
`innerHTML` bilan qayta chizadi; JS bilan "hydrate" qiladigan yechim har bir
qayta chizishdan keyin qayta chaqirishni talab qilardi va bitta unutilgan joy
ikonkasiz qolardi.

**Bir jihat:** `.ico { width: 1em; background: currentColor }` — shu tufayli
o'lcham `font-size`, rang esa `color` bilan boshqariladi, ya'ni eski
inline uslublar (`style="font-size:20px; color:#fff"`) o'zgarishsiz ishlaydi.

Yo'l-yo'lakay:
- `material-symbols-outlined.ttf` (1.4 MB) o'chirildi — endi kerak emas
- Katalog ikonkasi `layout-grid` dan `boxes` ga o'tdi: u Dashboard ikonkasi
  bilan bir xil katakcha bo'lib ko'rinardi

**Diqqat — bitta tuzoq:** SVG atributlari BIR tirnoqda bo'lishi shart.
Qo'shtirnoq `url("...")` ni erta yopib, niqobni yaroqsiz qiladi va ikonka
umuman chizilmaydi. Birinchi urinishda aynan shu bo'lgan edi.

---

## 16. Yorug' mavzu va dizayn qatlami

### Yorug' mavzu

Uch holat: **Avto** (tizim sozlamasiga ergashadi) · **Yorug'** · **Qorong'i**.
Tanlov `localStorage` da; yon panelning pastida segment tugma.

Mavzu `<head>` dagi inline skriptda, CSS'dan OLDIN qo'yiladi — aks holda
yorug' mavzuni tanlagan foydalanuvchi har safar bir lahza qorong'i chaqnashni
ko'radi.

Yorug' palitra qorong'ining oqartirilgani EMAS, alohida to'plam. Ikki sabab:

1. **Yashil ko'chib yuradi.** Qorong'ida yorug' yashil (`#4cdf9f`) o'qiladi,
   oq fonda u ko'rinmaydi — shuning uchun yorug'da yashil TO'Q (`#00694a`).
2. **Balandlik teskari.** Qorong'ida yuqoridagi yuza yorug'roq; yorug'da esa
   OQ kartochka biroz to'q sahifa fonida turadi.

Barcha matn juftliklari o'lchandi: eng pasti 4.70:1 (AA talabi 4.5).

### Yo'l-yo'lakay topilgan uchta xato

1. **`color: var(--primary)` matn uchun ishlatilgan edi** — 23 joyda.
   Kodning o'z qoidasiga ko'ra `--primary` to'ldirish uchun, matn uchun
   `--primary-text`. Bu **qorong'i mavzuni ham** yaxshiladi: yashil matn
   4.3:1 dan ~9:1 ga chiqdi.
2. **Grafikda poyga** — `chartLoading` qorovuli ikkinchi chaqiruvni butunlay
   tashlab yuborardi va bo'limlar orasida tez o'tilganda ekranda skelet
   qolib ketardi. Endi eng oxirgi so'rov g'olib bo'ladi.
3. **Qattiq yozilgan ranglar** — 50 ta almashtirildi (soyalar, nishonlar,
   modal parda, toast, brauzer avto-to'ldirishi).

### Dizayn: tekislikni yo'qotish

- **Don (grain)** — `body::after` da juda yengil shovqin qatlami. Sof tekis
  fon sterilga o'xshaydi; bu qatlam ko'zga ko'rinmaydi, lekin yuzaga "qog'oz"
  hissi beradi
- **Ikki qatlamli soyalar** — yaqin va zich "tegish" soyasi chekkani
  belgilaydi, keng va yumshoq soyasi buyumni yuzadan ko'taradi. Bitta qatlam
  bilan kartochka yo qirqilgan qog'ozdek yassi, yo tuman ichida suzayotgandek
  chiqadi. Rang qora emas, fon ohangida: oq fonda qora soya kir dog'dek
  ko'rinadi

### Yorug' fon: o'lchangan, taxmin qilinmagan

Birinchi urinishda sahifa foni `#e8ece9` edi — ekranda **rgb(232,236,233)**,
ya'ni kulrang bo'lib butun panelni bosib turardi. Piksel darajasida o'lchandi
va ochartirildi: endi **rgb(244,247,245)**, deyarli oq.

Fon ochargani uchun oq kartochka endi fonning to'qligi bilan emas, **soya
bilan** ajraladi. Shuning uchun soyalar qayta ishlandi va ular haqiqatan
ishlayotgani o'lchab tekshirildi: kartochka ostida 230 dan 244 gacha yumshoq
o'tish (31 birlik chuqurlik), qorong'ida 28 dan 48 gacha.

Yo'l-yo'lakay: don qatlami fonni qoraytiryapti degan shubha bor edi — o'lchov
uni rad etdi (±1 birlik), muammo fon tokenining o'zida ekan.

**Topilgan xato:** kartochka soyalari ikki joyda ta'riflangan edi va CSS'da
keyingi turgani yutib, tokenlarni bekor qilardi. Endi bitta manba.
- **Kursor ostida jonlanish** — kartochka soyasi kuchayadi va chegara
  yashillashadi
- **Tabular raqamlar** — jadvalda summalar ustun bo'ylab sakramaydi
- **Klaviatura fokusi** — ilgari umuman ko'rinmasdi, panelni sichqonchasiz
  ishlatib bo'lmasdi
- **Bosilganda** 1px pastga siljish — jismoniy javob hissi
