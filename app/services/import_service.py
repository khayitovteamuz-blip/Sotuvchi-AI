"""
Catalog import — the fastest way to onboard a business.

Typing 200 products into a form is the biggest barrier to a shop actually
using the product, but every one of them already keeps a price list in Excel.
So: accept their file as-is. Column headers are matched loosely across Uzbek,
Russian and English, bad rows are reported instead of aborting the whole
import, and re-importing updates existing products rather than duplicating.
"""
import csv
import io
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


def _register(field: str, *names: str) -> None:
    for n in names:
        COLUMN_ALIASES[n] = field


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


def _norm_header(h: Any) -> str:
    s = str(h or "").strip().lower()
    for ch in "ʻʼ‘’`´'\"":
        s = s.replace(ch, "")
    return re.sub(r"\s+", " ", s)


def _parse_price(v: Any) -> Optional[float]:
    """Accept 15 200 000 / 15,200,000 / 15200000.50 / "15 200 000 so'm"."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s:
        return None
    s = re.sub(r"[^\d,.\-]", "", s)          # drop currency words and spaces
    if "," in s and "." in s:                 # 1,234.56 -> 1234.56
        s = s.replace(",", "")
    elif s.count(",") == 1 and len(s.split(",")[-1]) <= 2:
        s = s.replace(",", ".")               # 1234,56 -> 1234.56
    else:
        s = s.replace(",", "")
    try:
        return float(s)
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
def read_rows(filename: str, content: bytes) -> Tuple[List[str], List[List[Any]]]:
    """Return (headers, rows) from an .xlsx/.xls or .csv upload."""
    lower = (filename or "").lower()
    if lower.endswith((".xlsx", ".xlsm")):
        return _read_xlsx(content)
    if lower.endswith(".csv") or lower.endswith(".txt"):
        return _read_csv(content)
    if lower.endswith(".xls"):
        raise ValueError("Eski .xls format qo'llab-quvvatlanmaydi. Excel'da 'Save As → .xlsx' qiling.")
    raise ValueError("Faqat .xlsx yoki .csv fayllar qabul qilinadi.")


def _read_xlsx(content: bytes) -> Tuple[List[str], List[List[Any]]]:
    import openpyxl
    wb = openpyxl.load_workbook(io.BytesIO(content), read_only=True, data_only=True)
    ws = wb.active
    rows = []
    for row in ws.iter_rows(values_only=True):
        rows.append(list(row))
        if len(rows) > MAX_ROWS + 1:
            break
    wb.close()
    if not rows:
        raise ValueError("Fayl bo'sh.")
    return [str(h or "") for h in rows[0]], rows[1:]


def _read_csv(content: bytes) -> Tuple[List[str], List[List[Any]]]:
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
    rows = [r for _, r in zip(range(MAX_ROWS + 1), reader, strict=False)]
    if not rows:
        raise ValueError("Fayl bo'sh.")
    return rows[0], rows[1:]


def map_columns(headers: List[str]) -> Dict[str, int]:
    """Map canonical field -> column index, ignoring unknown columns."""
    mapping: Dict[str, int] = {}
    for idx, h in enumerate(headers):
        field = COLUMN_ALIASES.get(_norm_header(h))
        if field and field not in mapping:
            mapping[field] = idx
    return mapping


# ─── Import ───────────────────────────────────────────────────────────────────
async def import_products(
    session: AsyncSession,
    tenant_id: str,
    filename: str,
    content: bytes,
    dry_run: bool = False,
) -> Dict[str, Any]:
    headers, rows = read_rows(filename, content)
    mapping = map_columns(headers)

    if "name" not in mapping or "price" not in mapping:
        return {
            "success": False,
            "error": "Faylda 'Nomi' va 'Narxi' ustunlari topilmadi.",
            "found_columns": [h for h in headers if h],
            "expected": "Nomi, Narxi, Kategoriya, Tavsif, Qoldiq (yoki inglizcha/ruscha nomlari)",
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

    added, updated, skipped = 0, 0, 0
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
        image_url = str(cell(row, "image_url") or "").strip() or None
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
            if image_url:
                target.image_url = image_url
                target.image_urls = [image_url]
            updated += 1
        else:
            pid = raw_id or f"PROD-{uuid.uuid4().hex[:8].upper()}"
            p = Product(
                id=pid, tenant_id=tenant_id, name=name, category=category,
                price=price, currency=currency, description=description,
                image_url=image_url, image_urls=[image_url] if image_url else [],
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
