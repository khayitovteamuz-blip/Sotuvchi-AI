"""
Generate a 100-product demo catalog (.xlsx + .csv) for testing the importer,
the trigram search and the AI agent with a realistic Uzbek shop.

Every image URL here was checked to return HTTP 200 before being committed.

Run:  .venv/bin/python -m scripts.make_demo_catalog
Out:  data/namuna-katalog-100.xlsx  va  data/namuna-katalog-100.csv
"""

from app.core.config import BASE_DIR

IMG = "https://images.unsplash.com/{}?w=600&auto=format&fit=crop&q=80"

# (name, category, price UZS, stock, description, unsplash photo id)
PRODUCTS = [
    # ─── Smartfonlar (14) ───
    ("iPhone 15 Pro Max 256GB", "Smartfonlar", 15200000, 8, "Titan korpus, A17 Pro chip, 48MP kamera", "photo-1695048133142-1a20484d2569"),
    ("iPhone 15 128GB", "Smartfonlar", 11500000, 12, "A16 Bionic, Dynamic Island, USB-C", "photo-1695048133142-1a20484d2569"),
    ("iPhone 14 128GB", "Smartfonlar", 9200000, 6, "Rasmiy kafolat, ideal holat", "photo-1592286927505-1def25115558"),
    ("Samsung Galaxy S24 Ultra 512GB", "Smartfonlar", 16800000, 5, "S Pen, 200MP kamera, Snapdragon 8 Gen 3", "photo-1511707171634-5f897ff02aa9"),
    ("Samsung Galaxy S24 256GB", "Smartfonlar", 12400000, 9, "Kompakt flagman, AMOLED 120Hz", "photo-1511707171634-5f897ff02aa9"),
    ("Samsung Galaxy A55 128GB", "Smartfonlar", 4900000, 20, "O'rta segment, 50MP kamera", "photo-1610945265064-0e34e5519bbf"),
    ("Samsung Galaxy A35 128GB", "Smartfonlar", 3800000, 25, "Arzon va ishonchli", "photo-1610945265064-0e34e5519bbf"),
    ("Xiaomi Redmi Note 13 Pro", "Smartfonlar", 3200000, 30, "200MP kamera, 67W tez quvvatlash", "photo-1598327105666-5b89351aff97"),
    ("Xiaomi Redmi 13C 128GB", "Smartfonlar", 1750000, 40, "Byudjet segment, katta batareya", "photo-1598327105666-5b89351aff97"),
    ("Xiaomi 14 Ultra", "Smartfonlar", 14500000, 4, "Leica optikasi, Snapdragon 8 Gen 3", "photo-1592750475338-74b7b21085ab"),
    ("Google Pixel 8 Pro", "Smartfonlar", 13200000, 3, "Eng yaxshi kamera AI si", "photo-1598327105666-5b89351aff97"),
    ("Honor X9b 256GB", "Smartfonlar", 3900000, 15, "Chidamli ekran, 5800mAh", "photo-1610945265064-0e34e5519bbf"),
    ("Infinix Note 40 Pro", "Smartfonlar", 2900000, 18, "AMOLED, 45W quvvat", "photo-1598327105666-5b89351aff97"),
    ("Tecno Camon 30", "Smartfonlar", 2600000, 14, "Selfi uchun ideal", "photo-1610945265064-0e34e5519bbf"),

    # ─── Noutbuklar (12) ───
    ("MacBook Air M3 15-inch 16/512GB", "Noutbuklar", 18900000, 5, "M3 chip, 18 soat batareya, Liquid Retina", "photo-1517336714731-489689fd1ca8"),
    ("MacBook Air M2 13-inch 8/256GB", "Noutbuklar", 13500000, 7, "Yengil va kuchli, MagSafe", "photo-1517336714731-489689fd1ca8"),
    ("MacBook Pro 14 M3 Pro", "Noutbuklar", 26000000, 3, "Professional ish uchun, ProMotion", "photo-1496181133206-80ce9b88a853"),
    ("Lenovo IdeaPad Slim 3", "Noutbuklar", 6900000, 12, "Ryzen 5, 16GB RAM, o'quv uchun", "photo-1496181133206-80ce9b88a853"),
    ("Lenovo ThinkPad E14 Gen 5", "Noutbuklar", 11200000, 6, "Biznes noutbuk, ishonchli klaviatura", "photo-1496181133206-80ce9b88a853"),
    ("Asus VivoBook 15 OLED", "Noutbuklar", 8400000, 9, "OLED ekran, Intel Core i5", "photo-1517336714731-489689fd1ca8"),
    ("Asus ROG Strix G16", "Noutbuklar", 19500000, 4, "Gaming, RTX 4060, 165Hz", "photo-1603302576837-37561b2e2302"),
    ("HP Pavilion 15", "Noutbuklar", 7600000, 11, "Kundalik ishlar uchun", "photo-1496181133206-80ce9b88a853"),
    ("HP Victus 16", "Noutbuklar", 13800000, 5, "O'yin va montaj uchun, RTX 4050", "photo-1603302576837-37561b2e2302"),
    ("Dell Inspiron 15 3520", "Noutbuklar", 7200000, 8, "Arzon va bardoshli", "photo-1496181133206-80ce9b88a853"),
    ("Acer Aspire 5", "Noutbuklar", 6500000, 10, "Talabalar uchun eng yaxshi tanlov", "photo-1517336714731-489689fd1ca8"),
    ("MSI Katana 15", "Noutbuklar", 15900000, 3, "Gaming noutbuk, RTX 4060", "photo-1603302576837-37561b2e2302"),

    # ─── Planshetlar (6) ───
    ("iPad Pro 11 M4 256GB", "Planshetlar", 15800000, 4, "M4 chip, Ultra Retina XDR", "photo-1544244015-0df4b3ffc6b0"),
    ("iPad Air 11 M2 128GB", "Planshetlar", 9400000, 7, "Apple Pencil Pro qo'llab-quvvatlaydi", "photo-1544244015-0df4b3ffc6b0"),
    ("iPad 10.9 64GB", "Planshetlar", 5900000, 12, "O'qish va ko'ngilochar uchun", "photo-1544244015-0df4b3ffc6b0"),
    ("Samsung Galaxy Tab S9", "Planshetlar", 11200000, 5, "AMOLED, S Pen bilan", "photo-1585790050230-5dd28404ccb9"),
    ("Samsung Galaxy Tab A9+", "Planshetlar", 3200000, 15, "Bolalar va o'quv uchun", "photo-1585790050230-5dd28404ccb9"),
    ("Xiaomi Pad 6", "Planshetlar", 4100000, 10, "144Hz ekran, arzon narx", "photo-1585790050230-5dd28404ccb9"),

    # ─── Aqlli soatlar (8) ───
    ("Apple Watch Series 9 GPS 45mm", "Aqlli soatlar", 5400000, 10, "Double Tap, yorqin displey", "photo-1508685096489-7aacd43bd3b1"),
    ("Apple Watch Ultra 2", "Aqlli soatlar", 11800000, 4, "Titanium, 36 soat batareya", "photo-1508685096489-7aacd43bd3b1"),
    ("Apple Watch SE 2 40mm", "Aqlli soatlar", 3200000, 14, "Arzon Apple Watch varianti", "photo-1546868871-7041f2a55e12"),
    ("Samsung Galaxy Watch 6", "Aqlli soatlar", 3900000, 9, "Salomatlik sensorlari, AMOLED", "photo-1546868871-7041f2a55e12"),
    ("Xiaomi Watch S3", "Aqlli soatlar", 1450000, 20, "14 kun batareya", "photo-1546868871-7041f2a55e12"),
    ("Xiaomi Mi Band 8", "Aqlli soatlar", 450000, 45, "Eng ommabop fitnes bilaguzuk", "photo-1575311373937-040b8e1fd5b6"),
    ("Amazfit GTR 4", "Aqlli soatlar", 2100000, 12, "GPS, 14 kun ishlash", "photo-1546868871-7041f2a55e12"),
    ("Huawei Band 9", "Aqlli soatlar", 590000, 30, "Yengil va nafis dizayn", "photo-1575311373937-040b8e1fd5b6"),

    # ─── Audio texnika (12) ───
    ("AirPods Pro 2 (USB-C)", "Audio texnika", 2950000, 25, "ANC, Shaffoflik rejimi, MagSafe", "photo-1600294037681-c80b4cb5b434"),
    ("AirPods 4", "Audio texnika", 1850000, 20, "Yangi dizayn, yaxshilangan ovoz", "photo-1600294037681-c80b4cb5b434"),
    ("AirPods Max", "Audio texnika", 7200000, 3, "Premium quloqchin, Hi-Fi ovoz", "photo-1505740420928-5e560c06d30e"),
    ("Sony WH-1000XM5", "Audio texnika", 4300000, 8, "Eng yaxshi shovqin bostirish", "photo-1505740420928-5e560c06d30e"),
    ("Sony WF-1000XM5", "Audio texnika", 3100000, 10, "Simsiz TWS quloqchin", "photo-1600294037681-c80b4cb5b434"),
    ("JBL Tune 770NC", "Audio texnika", 1250000, 18, "70 soat batareya, ANC", "photo-1505740420928-5e560c06d30e"),
    ("JBL Flip 6 kolonka", "Audio texnika", 1350000, 15, "Suv o'tkazmaydigan portativ kolonka", "photo-1608043152269-423dbba4e7e1"),
    ("JBL Charge 5", "Audio texnika", 1950000, 12, "20 soat ishlaydi, powerbank rejimi", "photo-1608043152269-423dbba4e7e1"),
    ("Marshall Emberton II", "Audio texnika", 2400000, 6, "Klassik dizayn, kuchli bas", "photo-1608043152269-423dbba4e7e1"),
    ("Xiaomi Redmi Buds 5", "Audio texnika", 350000, 40, "Arzon va sifatli TWS", "photo-1600294037681-c80b4cb5b434"),
    ("Anker Soundcore Life Q30", "Audio texnika", 890000, 16, "Byudjet ANC quloqchin", "photo-1505740420928-5e560c06d30e"),
    ("Bose QuietComfort Ultra", "Audio texnika", 5600000, 4, "Premium shovqin bostirish", "photo-1505740420928-5e560c06d30e"),

    # ─── Aksessuarlar (12) ───
    ("Anker PowerBank 20000mAh", "Aksessuarlar", 450000, 35, "Tez quvvatlash, 2 ta port", "photo-1609091839311-d5365f9ff1c5"),
    ("Anker PowerBank 10000mAh", "Aksessuarlar", 290000, 45, "Yupqa va yengil", "photo-1609091839311-d5365f9ff1c5"),
    ("Apple MagSafe quvvatlagich", "Aksessuarlar", 620000, 20, "15W simsiz quvvatlash", "photo-1583863788434-e58a36330cf0"),
    ("USB-C 65W quvvatlagich", "Aksessuarlar", 240000, 50, "Noutbuk va telefon uchun", "photo-1583863788434-e58a36330cf0"),
    ("Lightning kabel 2m", "Aksessuarlar", 95000, 80, "Original sifat, mustahkam", "photo-1583863788434-e58a36330cf0"),
    ("USB-C kabel 100W 2m", "Aksessuarlar", 120000, 70, "Tez quvvatlash va data", "photo-1583863788434-e58a36330cf0"),
    ("iPhone 15 Pro silikon g'ilof", "Aksessuarlar", 180000, 60, "MagSafe bilan mos", "photo-1601593346740-925612772716"),
    ("Himoya oynasi 9H", "Aksessuarlar", 45000, 120, "Barcha modellar uchun", "photo-1601593346740-925612772716"),
    ("Avtomobil telefon ushlagichi", "Aksessuarlar", 85000, 55, "Magnitli, mustahkam", "photo-1601593346740-925612772716"),
    ("Simsiz sichqoncha Logitech M240", "Aksessuarlar", 210000, 30, "Bluetooth, jimjit tugmalar", "photo-1527864550417-7fd91fc51a46"),
    ("Klaviatura Logitech K380", "Aksessuarlar", 380000, 22, "3 ta qurilmaga ulanadi", "photo-1587829741301-dc798b83add3"),
    ("Noutbuk sumkasi 15.6", "Aksessuarlar", 190000, 40, "Suv o'tkazmaydigan mato", "photo-1553062407-98eeb64c6a62"),

    # ─── Televizorlar (7) ───
    ("Samsung 55\" QLED Q60C", "Televizorlar", 9800000, 6, "4K QLED, Tizen Smart TV", "photo-1593359677879-a4bb92f829d1"),
    ("Samsung 43\" Crystal UHD", "Televizorlar", 5200000, 10, "4K, HDR10+", "photo-1593359677879-a4bb92f829d1"),
    ("LG 55\" OLED C3", "Televizorlar", 16500000, 3, "OLED evo, 120Hz gaming", "photo-1593359677879-a4bb92f829d1"),
    ("LG 50\" UHD UR78", "Televizorlar", 6100000, 8, "webOS, AI ProcessorPRO", "photo-1461151304267-38535e780c79"),
    ("Xiaomi TV A2 43\"", "Televizorlar", 3900000, 12, "Google TV, arzon narx", "photo-1461151304267-38535e780c79"),
    ("Artel 43\" Smart TV", "Televizorlar", 3200000, 15, "Mahalliy ishlab chiqarish, kafolat", "photo-1461151304267-38535e780c79"),
    ("TCL 65\" QLED C645", "Televizorlar", 11200000, 4, "Katta ekran, Dolby Vision", "photo-1593359677879-a4bb92f829d1"),

    # ─── Maishiy texnika (14) ───
    ("Dyson V15 Detect changyutgich", "Maishiy texnika", 9800000, 4, "Simsiz, lazer chang detektori", "photo-1558618666-fcd25c85cd64"),
    ("Xiaomi Robot Vacuum S10", "Maishiy texnika", 3900000, 7, "Robot changyutgich, LDS navigatsiya", "photo-1558618666-fcd25c85cd64"),
    ("Philips kofe mashinasi 3200", "Maishiy texnika", 4200000, 5, "Avtomatik, LatteGo tizimi", "photo-1495474472287-4d71bcdd2085"),
    ("Nespresso Vertuo Next", "Maishiy texnika", 1900000, 9, "Kapsulali kofe qaynatgich", "photo-1495474472287-4d71bcdd2085"),
    ("Samsung mikroto'lqinli pech 23L", "Maishiy texnika", 1450000, 14, "Ceramic Enamel ichki qoplama", "photo-1585659722983-3a675dabf23d"),
    ("Bosch kir yuvish mashinasi 7kg", "Maishiy texnika", 6800000, 6, "EcoSilence Drive, A+++", "photo-1626806787461-102c1bfaaea1"),
    ("LG kir yuvish mashinasi 8kg", "Maishiy texnika", 7400000, 5, "AI DD texnologiyasi, bug'", "photo-1626806787461-102c1bfaaea1"),
    ("Samsung muzlatgich 360L", "Maishiy texnika", 9200000, 4, "No Frost, Digital Inverter", "photo-1571175443880-49e1d25b2bc5"),
    ("Artel muzlatgich 300L", "Maishiy texnika", 5100000, 8, "Mahalliy, 3 yil kafolat", "photo-1571175443880-49e1d25b2bc5"),
    ("Philips havo namlagich", "Maishiy texnika", 1250000, 12, "Xona havosini yaxshilaydi", "photo-1585659722983-3a675dabf23d"),
    ("Tefal elektr choynak 1.7L", "Maishiy texnika", 320000, 30, "Zanglamaydigan po'lat", "photo-1585659722983-3a675dabf23d"),
    ("Bosch blender 800W", "Maishiy texnika", 680000, 18, "Kuchli motor, ko'p rejimli", "photo-1585659722983-3a675dabf23d"),
    ("Xiaomi havo tozalagich 4 Lite", "Maishiy texnika", 2100000, 9, "HEPA filtr, ilova bilan", "photo-1585659722983-3a675dabf23d"),
    ("Redmond multipishirgich", "Maishiy texnika", 890000, 16, "40 ta dastur, 5L hajm", "photo-1585659722983-3a675dabf23d"),

    # ─── Fotoapparatlar (5) ───
    ("Canon EOS R50 kit", "Fotoapparatlar", 9800000, 4, "Mirrorless, 24MP, 4K video", "photo-1502920917128-1aa500764cbd"),
    ("Sony Alpha A6400 kit", "Fotoapparatlar", 12400000, 3, "Tez avtofokus, bloger uchun", "photo-1502920917128-1aa500764cbd"),
    ("Nikon Z50 kit", "Fotoapparatlar", 11200000, 2, "APS-C mirrorless", "photo-1502920917128-1aa500764cbd"),
    ("GoPro HERO12 Black", "Fotoapparatlar", 5600000, 6, "5.3K video, suvga chidamli", "photo-1526170375885-4d8ecf77b99f"),
    ("DJI Osmo Pocket 3", "Fotoapparatlar", 6200000, 5, "Gimbal kamera, 1-dyuym sensor", "photo-1526170375885-4d8ecf77b99f"),

    # ─── O'yin konsollari (4) ───
    ("PlayStation 5 Slim", "O'yin konsollari", 8900000, 6, "Disk versiyasi, DualSense", "photo-1606813907291-d86efa9b94db"),
    ("PlayStation 5 DualSense joystik", "O'yin konsollari", 950000, 20, "Haptik javob, adaptiv triggerlar", "photo-1606813907291-d86efa9b94db"),
    ("Xbox Series S 512GB", "O'yin konsollari", 4900000, 8, "Kompakt, Game Pass uchun ideal", "photo-1621259182978-fbf93132d53d"),
    ("Nintendo Switch OLED", "O'yin konsollari", 5200000, 5, "7 dyuym OLED ekran", "photo-1578303512597-81e6cc155b3e"),

    # ─── Kiyim va poyabzal (6) ───
    ("Nike Air Max 270", "Kiyim va poyabzal", 1850000, 15, "Original, qulay va yengil", "photo-1542291026-7eec264c27ff"),
    ("Adidas Ultraboost 22", "Kiyim va poyabzal", 2100000, 12, "Yugurish uchun professional", "photo-1600269452121-4f2416e55c28"),
    ("Nike Dri-FIT sport futbolka", "Kiyim va poyabzal", 420000, 40, "Terni tez quritadi", "photo-1521572163474-6864f9cf17ab"),
    ("Adidas sport shim", "Kiyim va poyabzal", 580000, 25, "Paxta aralashmasi, qulay", "photo-1521572163474-6864f9cf17ab"),
    ("Puma RS-X krossovka", "Kiyim va poyabzal", 1450000, 18, "Zamonaviy dizayn", "photo-1600269452121-4f2416e55c28"),
    ("The North Face kurtka", "Kiyim va poyabzal", 2900000, 8, "Qish uchun issiq va yengil", "photo-1551028719-00167b16eac5"),
]


def build_rows():
    rows = []
    for name, cat, price, stock, desc, photo in PRODUCTS:
        rows.append([name, cat, price, stock, desc, IMG.format(photo)])
    return rows


def main() -> None:
    import openpyxl

    rows = build_rows()
    header = ["Nomi", "Kategoriya", "Narxi", "Qoldiq", "Tavsif", "Rasm"]
    out_dir = BASE_DIR / "data"
    out_dir.mkdir(exist_ok=True)

    # ── xlsx ──
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Katalog"
    ws.append(header)
    for r in rows:
        ws.append(r)
    for col, width in zip("ABCDEF", (38, 20, 14, 10, 52, 70)):
        ws.column_dimensions[col].width = width
    ws.freeze_panes = "A2"
    xlsx_path = out_dir / "namuna-katalog-100.xlsx"
    wb.save(xlsx_path)

    # ── csv (BOM so Excel opens Uzbek text correctly) ──
    import csv
    csv_path = out_dir / "namuna-katalog-100.csv"
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(header)
        w.writerows(rows)

    cats = {}
    for _, c, *_ in PRODUCTS:
        cats[c] = cats.get(c, 0) + 1

    print(f"✅ {len(rows)} ta mahsulot yaratildi\n")
    print(f"   {xlsx_path}")
    print(f"   {csv_path}\n")
    print("   Kategoriyalar:")
    for c, n in sorted(cats.items(), key=lambda x: -x[1]):
        print(f"     {c:<22} {n} ta")
    total = sum(p[2] for p in PRODUCTS)
    print(f"\n   Narx oralig'i: {min(p[2] for p in PRODUCTS):,} — {max(p[2] for p in PRODUCTS):,} UZS")
    print(f"   Umumiy qiymat: {total:,} UZS")


if __name__ == "__main__":
    main()
