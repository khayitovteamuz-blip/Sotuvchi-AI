"""
Catalog import — the fastest way to onboard a business.

Typing 200 products into a form is the biggest barrier to a shop actually
using the product, but every one of them already keeps a price list in Excel.
So: accept their file as-is. Column headers are matched loosely across Uzbek,
Russian and English, bad rows are reported instead of aborting the whole
import, and re-importing updates existing products rather than duplicating.
"""
import asyncio
import csv
import io
import json
import logging
import re
import uuid
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Category, Product

logger = logging.getLogger("import_service")

MAX_ROWS = 5000

# Accepted header spellings -> canonical field.
COLUMN_ALIASES: Dict[str, str] = {}



# Cyrillic -> Latin, so "Наименование" and "Nomi" reach the same alias table.
# Longer sequences first: "щ" must win before "ш".
_CYR = [
    ("щ", "sh"), ("ш", "sh"), ("ч", "ch"), ("ц", "ts"), ("ю", "yu"), ("я", "ya"),
    ("ж", "j"), ("х", "x"), ("ъ", ""), ("ь", ""), ("ы", "i"), ("э", "e"),
    ("ё", "yo"), ("а", "a"), ("б", "b"), ("в", "v"), ("г", "g"), ("д", "d"),
    ("е", "e"), ("з", "z"), ("и", "i"), ("й", "y"), ("к", "k"), ("л", "l"),
    ("м", "m"), ("н", "n"), ("о", "o"), ("п", "p"), ("р", "r"), ("с", "s"),
    ("т", "t"), ("у", "u"), ("ф", "f"), ("қ", "q"), ("ғ", "g"), ("ҳ", "h"),
    ("ў", "o"),
]


def translit(s: str) -> str:
    """Cyrillic text to a Latin form, for matching only (not for display)."""
    out = s
    for cyr, lat in _CYR:
        out = out.replace(cyr, lat)
    return out


def _norm_header(h: Any) -> str:
    """Fold a header to a comparable form: case, quotes, spaces, script."""
    s = str(h or "").strip().lower()
    for ch in "ʻʼ‘’`´'\"«»":
        s = s.replace(ch, "")
    s = s.replace("\u00a0", " ")
    s = translit(s)
    s = re.sub(r"[^\w\s]+", " ", s)      # punctuation -> space
    return re.sub(r"\s+", " ", s).strip()


def _register(field: str, *names: str) -> None:
    """Register header spellings. Each is folded the same way an incoming
    header is, so a Cyrillic alias and its Latin form land on one key."""
    for n in names:
        COLUMN_ALIASES[_norm_header(n)] = field


_register("name", "nomi", "nom", "mahsulot", "mahsulot nomi", "maxsulot", "maxsulot nomi",
          "tovar", "name", "product", "product name", "title", "название", "наименование", "товар")
_register("price", "narx", "narxi", "narh", "narhi", "summa", "price", "cost", "amount",
          "цена", "стоимость")
_register("category", "kategoriya", "katalog", "turkum", "bo'lim", "bolim", "category",
          "категория", "раздел", "группа")
_register("description", "tavsif", "tafsif", "izoh", "batafsil", "description", "desc",
          "описание", "детали")
_register("stock_quantity", "qoldiq", "soni", "son", "miqdor", "ombor", "ombor qoldigi",
          "ombordagi soni", "stock", "quantity", "qty", "count", "остаток", "количество")
_register("id", "id", "kod", "artikul", "sku", "mahsulot id", "код", "артикул")
_register("currency", "valyuta", "currency", "valuta", "валюта")
_register("image_url", "rasm", "rasm url", "surat", "image", "image url", "photo",
          "picture", "фото", "изображение")

# "1.5 mln", "250 ming", "3 млн" — shorthand a price list often uses.
_SCALE = [
    (("mlrd", "milliard", "млрд", "миллиард"), 1_000_000_000),
    (("mln", "million", "млн", "миллион"), 1_000_000),
    (("ming", "тыс", "тысяч", "min", "k"), 1_000),
]


def _parse_price(v: Any) -> Optional[float]:
    """Accept the shapes a real price list uses.

    15 200 000 · 15,200,000 · 15.200.000 · 15'200'000 · 15200000.50
    "15 200 000 so'm" · "1.5 mln" · "250 ming" · "3 млн" · "1 500 000 UZS"
    """
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)

    s = str(v).strip().lower().replace("\u00a0", " ")
    if not s:
        return None

    # Multiplier written as a word, e.g. "1.5 mln"
    mult = 1
    for words, factor in _SCALE:
        if any(re.search(rf"(?<![a-z]){w}(?![a-z])", s) for w in words):
            mult = factor
            for w in words:
                s = re.sub(rf"(?<![a-z]){w}(?![a-z])", " ", s)
            break

    s = re.sub(r"[^\d,.\'\s-]", " ", s)      # drop currency words
    s = s.replace("'", "").replace(" ", "")   # 15'200'000 / 15 200 000

    if "," in s and "." in s:
        # The rightmost separator is the decimal one: 1.234,56 and 1,234.56
        s = s.replace("." if s.rfind(",") > s.rfind(".") else ",", "")
        s = s.replace(",", ".")
    elif s.count(",") == 1 and len(s.split(",")[-1]) in (1, 2):
        s = s.replace(",", ".")               # 1234,56
    elif s.count(".") > 1 or (s.count(".") == 1 and len(s.split(".")[-1]) == 3):
        s = s.replace(".", "")                # 15.200.000 is grouping, not decimal
    else:
        s = s.replace(",", "")

    try:
        return float(s) * mult
    except ValueError:
        return None


def _parse_int(v: Any, default: int = 0) -> int:
    if v is None or v == "":
        return default
    try:
        return int(float(re.sub(r"[^\d.\-]", "", str(v)) or default))
    except (ValueError, TypeError):
        return default


# ─── File readers ─────────────────────────────────────────────────────────────
def read_rows(
    filename: str, content: bytes
) -> Tuple[List[str], List[List[Any]], Dict[int, List[bytes]]]:
    """Return headers, rows and row-indexed embedded images."""
    lower = (filename or "").lower()
    if lower.endswith((".xlsx", ".xlsm")):
        return _read_xlsx(content)
    if lower.endswith(".csv") or lower.endswith(".txt"):
        return _read_csv(content)
    if lower.endswith(".xls"):
        raise ValueError("Eski .xls format qo'llab-quvvatlanmaydi. Excel'da 'Save As → .xlsx' qiling.")
    raise ValueError("Faqat .xlsx yoki .csv fayllar qabul qilinadi.")


_SHEET_ID_RE = re.compile(r"/spreadsheets/d/([a-zA-Z0-9_-]+)")
_GID_RE = re.compile(r"[#&?]gid=(\d+)")


async def fetch_google_sheet_csv(url: str) -> bytes:
    """Turn a normal Google Sheets share link into its CSV export and fetch it.

    No Google API key or OAuth: Sheets serves any tab as CSV over plain HTTP
    at .../export?format=csv, as long as the sheet is shared "anyone with the
    link can view" — the one step a non-technical shop owner can actually do
    themselves. A private sheet returns 200 with an HTML sign-in page instead
    of CSV, which is why the content-type is checked, not just the status.
    """
    m = _SHEET_ID_RE.search(url or "")
    if not m:
        raise ValueError(
            "Bu Google Sheets havolasiga o'xshamayapti. Jadvalni brauzerda oching va "
            "manzil qatoridagi (docs.google.com/spreadsheets/d/... bilan boshlanadigan) "
            "havolani to'liq nusxalang."
        )
    sheet_id = m.group(1)
    gid_m = _GID_RE.search(url)
    gid = gid_m.group(1) if gid_m else "0"
    export_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"

    import httpx
    try:
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            resp = await client.get(export_url)
    except httpx.HTTPError as e:
        raise ValueError(f"Google Sheets'ga ulanib bo'lmadi: {e}")

    if resp.status_code == 404:
        raise ValueError("Jadval topilmadi — havola noto'g'ri yoki jadval o'chirilgan.")
    if resp.status_code != 200:
        raise ValueError(f"Google Sheets xato qaytardi (kod {resp.status_code}).")
    if "text/csv" not in resp.headers.get("content-type", ""):
        raise ValueError(
            "Jadval hali ochiq emas. Google Sheets'da: yuqori o'ngdagi Ulashish "
            "(Share) tugmasi → \"Havolaga ega har kim\" (Anyone with the link) → "
            "\"Ko'ruvchi\" (Viewer) qilib qo'ying, keyin qayta urinib ko'ring."
        )
    return resp.content


def _read_xlsx(
    content: bytes,
) -> Tuple[List[str], List[List[Any]], Dict[int, List[bytes]]]:
    """Read the sheet and pick the header row.

    `read_only=False` on purpose: read-only mode does not expose embedded
    images, and a price list that carries its photos inside the file is exactly
    the case we want to support. The 10 MB upload cap keeps this affordable.
    """
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(content), data_only=True)
    ws = wb.active

    rows: List[List[Any]] = []
    for row in ws.iter_rows(values_only=True):
        rows.append(list(row))
        if len(rows) > MAX_ROWS + HEADER_SCAN_ROWS:
            break

    images = _extract_xlsx_images(ws)
    wb.close()
    if not rows:
        raise ValueError("Fayl bo'sh.")

    h = find_header_row(rows)
    headers = [str(x or "") for x in rows[h]]
    body = rows[h + 1:]

    # Images are anchored to absolute sheet rows; re-base them onto body rows.
    row_images = {
        abs_row - (h + 1): blobs
        for abs_row, blobs in images.items()
        if 0 <= abs_row - (h + 1) < len(body)
    }
    return headers, body, row_images


def _extract_xlsx_images(ws) -> Dict[int, List[bytes]]:
    """Map sheet row number -> image bytes anchored to that row."""
    found: Dict[int, List[bytes]] = {}
    for img in getattr(ws, "_images", []) or []:
        try:
            anchor = getattr(img, "anchor", None)
            frm = getattr(anchor, "_from", None)
            if frm is None:
                continue
            row = frm.row                     # 0-based in the anchor
            data = img._data() if callable(getattr(img, "_data", None)) else None
            if not data:
                continue
            found.setdefault(row, []).append(data)
        except Exception as e:                # noqa: BLE001 - a bad image must not stop the import
            logger.info("Rasmni o'qib bo'lmadi: %s", e)
    return found


def _read_csv(
    content: bytes,
) -> Tuple[List[str], List[List[Any]], Dict[int, List[bytes]]]:
    text = None
    for enc in ("utf-8-sig", "utf-8", "cp1251", "latin-1"):
        try:
            text = content.decode(enc)
            break
        except UnicodeDecodeError:
            continue
    if text is None:
        raise ValueError("Fayl kodlashini o'qib bo'lmadi.")

    sample = text[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
    except csv.Error:
        dialect = csv.excel
        dialect.delimiter = ";" if sample.count(";") > sample.count(",") else ","

    reader = csv.reader(io.StringIO(text), dialect)
    # strict=False on purpose: the range IS the cap — a file with more
    # rows than MAX_ROWS must stop, not raise.
    rows = [r for _, r in zip(range(MAX_ROWS + HEADER_SCAN_ROWS), reader, strict=False)]
    if not rows:
        raise ValueError("Fayl bo'sh.")
    h = find_header_row(rows)
    return rows[h], rows[h + 1:], {}


# How many leading rows to scan when hunting for the real header. Price lists
# often start with a title, a date, a blank line — the header is rarely row 1.
HEADER_SCAN_ROWS = 12


def _score_header(cells: List[Any]) -> int:
    """How many cells in this row look like known column names."""
    return sum(1 for c in cells if COLUMN_ALIASES.get(_norm_header(c)))


def find_header_row(rows: List[List[Any]]) -> int:
    """Index of the row that is most likely the header.

    Scoring beats "take row 1": a file that opens with "PRAYS LIST 2026" and a
    blank line would otherwise map its title as the product name and import
    one broken row per file.
    """
    best_i, best_score = 0, -1
    for i, row in enumerate(rows[:HEADER_SCAN_ROWS]):
        if not row:
            continue
        score = _score_header(row)
        filled = sum(1 for c in row if str(c or "").strip())
        # A header row has several named columns and few empty gaps.
        if score > best_score or (score == best_score and filled > sum(1 for c in rows[best_i] if str(c or "").strip())):
            best_i, best_score = i, score
    return best_i if best_score > 0 else 0


async def ai_map_columns(
    headers: List[str], sample_rows: List[List[Any]]
) -> Dict[str, int]:
    """Ask the model to map columns when the alias table could not.

    Only runs as a fallback, and only for the fields still missing. A price
    list can use any wording ("qiymati", "sotuv summasi", "цена за шт"), and
    hard-coding every variant is a losing game.
    """
    from app.core.config import settings
    if not settings.GEMINI_API_KEY:
        return {}

    preview = [
        [str(c)[:40] if c is not None else "" for c in (row or [])[: len(headers)]]
        for row in sample_rows[:3]
    ]
    prompt = (
        "Quyida mahsulotlar jadvalining ustun sarlavhalari va bir necha qator "
        "namunasi berilgan. Har bir ustun qaysi maydonga to'g'ri kelishini aniqla.\n\n"
        f"Sarlavhalar: {headers}\n"
        f"Namuna qatorlar: {preview}\n\n"
        "Faqat JSON qaytar, boshqa hech narsa yozma. Kalitlar shulardan bo'lsin: "
        "name, price, category, description, stock_quantity, id, currency, image_url. "
        "Qiymat — ustun indeksi (0 dan boshlab). Mos ustun yo'q bo'lsa, kalitni "
        'umuman qo\'shma. Masalan: {"name": 0, "price": 2}'
    )

    try:
        from google import genai
        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        resp = await asyncio.to_thread(
            client.models.generate_content,
            model=settings.IMPORT_MAP_MODEL,
            contents=prompt,
        )
        text = (resp.text or "").strip()
        text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.M).strip()
        raw = json.loads(text)
    except Exception as e:                      # noqa: BLE001 - fallback must never break the import
        logger.info("AI ustun tanish ishlamadi: %s", e)
        return {}

    allowed = {"name", "price", "category", "description",
               "stock_quantity", "id", "currency", "image_url"}
    out: Dict[str, int] = {}
    for k, v in (raw or {}).items():
        if k in allowed and isinstance(v, int) and 0 <= v < len(headers):
            out[k] = v
    return out


def map_columns(headers: List[str]) -> Dict[str, int]:
    """Map canonical field -> column index, ignoring unknown columns."""
    mapping: Dict[str, int] = {}
    for idx, h in enumerate(headers):
        field = COLUMN_ALIASES.get(_norm_header(h))
        if field and field not in mapping:
            mapping[field] = idx
    return mapping


MAX_IMAGES_PER_ROW = 5


def _store_image(tenant_id: str, blob: bytes) -> Optional[str]:
    """Save one embedded image and return its URL, or None if unusable."""
    try:
        from app.services import storage_service
        ext, content_type = storage_service.sniff(blob)
        if not ext:
            return None
        return storage_service.save_image(tenant_id, blob, ext, content_type)
    except Exception as e:                    # noqa: BLE001 - one bad image must not fail the row
        logger.info("Rasmni saqlab bo'lmadi: %s", e)
        return None


# ─── Import ───────────────────────────────────────────────────────────────────
async def import_products(
    session: AsyncSession,
    tenant_id: str,
    filename: str,
    content: bytes,
    dry_run: bool = False,
) -> Dict[str, Any]:
    headers, rows, row_images = read_rows(filename, content)
    mapping = map_columns(headers)
    ai_used = False

    # The alias table covers the common wordings. When it cannot find the two
    # required columns, let the model read the headers and a few sample rows —
    # that is what makes an arbitrary price list importable.
    if "name" not in mapping or "price" not in mapping:
        guessed = await ai_map_columns(headers, rows)
        if guessed:
            ai_used = True
            for field, idx in guessed.items():
                mapping.setdefault(field, idx)

    if "name" not in mapping or "price" not in mapping:
        return {
            "success": False,
            "error": "Faylda mahsulot nomi va narx ustunlari topilmadi.",
            "found_columns": [h for h in headers if h],
            "expected": "Nomi, Narxi, Kategoriya, Tavsif, Qoldiq (o'zbek, rus yoki ingliz tilida)",
        }

    def cell(row: List[Any], field: str) -> Any:
        i = mapping.get(field)
        if i is None or i >= len(row):
            return None
        return row[i]

    # Existing products, indexed by id and by lowercased name, so a re-import
    # updates rather than duplicating the catalog.
    res = await session.execute(select(Product).where(Product.tenant_id == tenant_id))
    existing = list(res.scalars().all())
    by_id = {p.id: p for p in existing}
    by_name = {p.name.strip().lower(): p for p in existing}

    added, updated, skipped, embedded_saved = 0, 0, 0, 0
    errors: List[Dict[str, Any]] = []
    seen_categories = set()

    for n, row in enumerate(rows, start=2):  # header is row 1
        if not row or all(c in (None, "") for c in row):
            continue
        if added + updated >= MAX_ROWS:
            errors.append({"row": n, "error": f"Limit {MAX_ROWS} qatordan oshdi — qolganlari o'tkazib yuborildi."})
            break

        name = str(cell(row, "name") or "").strip()
        price = _parse_price(cell(row, "price"))

        if not name:
            skipped += 1
            errors.append({"row": n, "error": "Nomi bo'sh"})
            continue
        if price is None or price < 0:
            skipped += 1
            errors.append({"row": n, "error": f"Narxi noto'g'ri: {cell(row, 'price')!r}", "name": name})
            continue

        category = str(cell(row, "category") or "").strip()
        description = str(cell(row, "description") or "").strip()
        qty = _parse_int(cell(row, "stock_quantity"), 0)
        currency = str(cell(row, "currency") or "UZS").strip().upper() or "UZS"
        # A cell can hold several links: "a.jpg, b.jpg" or newline-separated.
        raw_img = str(cell(row, "image_url") or "").strip()
        urls = [u.strip() for u in re.split(r"[,;\n|]+", raw_img) if u.strip().startswith("http")]

        # Images embedded in the sheet itself win: they are the shop's own
        # photos, while a link may point anywhere and can rot.
        for blob in row_images.get(n - 2, [])[:MAX_IMAGES_PER_ROW]:
            saved = _store_image(tenant_id, blob)
            if saved:
                urls.insert(0, saved)
                embedded_saved += 1

        urls = list(dict.fromkeys(urls))[:MAX_IMAGES_PER_ROW]
        image_url = urls[0] if urls else None
        raw_id = str(cell(row, "id") or "").strip()

        target = by_id.get(raw_id) if raw_id else by_name.get(name.lower())

        if target:
            target.name = name
            target.price = price
            target.currency = currency
            if category:
                target.category = category
            if description:
                target.description = description
            target.stock_quantity = qty
            target.in_stock = qty > 0
            if urls:
                target.image_url = image_url
                target.image_urls = urls
            updated += 1
        else:
            pid = raw_id or f"PROD-{uuid.uuid4().hex[:8].upper()}"
            p = Product(
                id=pid, tenant_id=tenant_id, name=name, category=category,
                price=price, currency=currency, description=description,
                image_url=image_url, image_urls=urls,
                in_stock=qty > 0, stock_quantity=qty,
            )
            session.add(p)
            by_id[pid] = p
            by_name[name.lower()] = p
            added += 1

        if category:
            seen_categories.add(category)

    # Create any categories the file introduced, so the catalog UI groups properly
    new_categories = 0
    if seen_categories and not dry_run:
        cres = await session.execute(select(Category).where(Category.tenant_id == tenant_id))
        have = {c.name.strip().lower() for c in cres.scalars().all()}
        for cname in sorted(seen_categories):
            if cname.strip().lower() not in have:
                session.add(Category(
                    id=f"cat-{uuid.uuid4().hex[:8]}", tenant_id=tenant_id,
                    name=cname, icon="📦",
                ))
                new_categories += 1

    if dry_run:
        await session.rollback()
    else:
        await session.commit()

    return {
        "success": True,
        "dry_run": dry_run,
        "ai_mapping": ai_used,
        "images_saved": embedded_saved,
        "added": added,
        "updated": updated,
        "skipped": skipped,
        "new_categories": new_categories,
        "total_rows": added + updated + skipped,
        "matched_columns": {k: headers[v] for k, v in mapping.items() if v < len(headers)},
        "ignored_columns": [
            h for i, h in enumerate(headers)
            if h and i not in mapping.values()
        ],
        "errors": errors[:25],
        "error_count": len(errors),
    }


def build_template_csv() -> str:
    """A starter file in the exact shape the importer expects."""
    return (
        "Nomi,Kategoriya,Narxi,Qoldiq,Tavsif,Rasm\n"
        "iPhone 15 Pro Max 256GB,Smartfonlar,15200000,8,Titan korpus va A17 Pro chip,\n"
        "AirPods Pro 2 (USB-C),Aksessuarlar,2950000,15,Shovqinni bekor qilish funksiyasi bilan,\n"
        "MacBook Air M3 15-inch,Noutbuklar,18900000,5,M3 protsessor va 18 soat batareya,\n"
    )


# ─── Export ───────────────────────────────────────────────────────────────────
EXPORT_COLUMNS = [
    ("id", "ID"),
    ("name", "Nomi"),
    ("category", "Kategoriya"),
    ("price", "Narxi"),
    ("currency", "Valyuta"),
    ("stock_quantity", "Qoldiq"),
    ("description", "Tavsif"),
    ("image_url", "Rasm"),
]


def build_export_xlsx(products: List[Product]) -> bytes:
    """Catalog as .xlsx, shaped so it can be edited and imported straight back.

    Same column names the importer recognises: edit the file, upload it, and
    the ID column makes it an update rather than a second copy of the catalog.
    """
    import openpyxl
    from openpyxl.styles import Font

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Katalog"

    ws.append([label for _, label in EXPORT_COLUMNS])
    for cell in ws[1]:
        cell.font = Font(bold=True)

    for p in products:
        urls = p.image_urls or ([p.image_url] if p.image_url else [])
        ws.append([
            p.id,
            p.name,
            p.category or "",
            float(p.price or 0),
            p.currency or "UZS",
            int(p.stock_quantity or 0),
            p.description or "",
            ", ".join(u for u in urls if u),
        ])

    for col, width in zip("ABCDEFGH", (18, 40, 20, 14, 10, 10, 46, 40), strict=True):
        ws.column_dimensions[col].width = width
    ws.freeze_panes = "A2"

    buf = io.BytesIO()
    wb.save(buf)
    wb.close()
    return buf.getvalue()
