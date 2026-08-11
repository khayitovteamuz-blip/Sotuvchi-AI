import os
import logging
from typing import List, Optional
from app.models.schema import Product, Order
from app.core.config import settings

logger = logging.getLogger("sheets_service")


class GoogleSheetsService:
    def __init__(self):
        self.client = None
        self.spreadsheet = None
        self.reason: Optional[str] = None   # why it is not connected, if it isn't
        self._initialize()

    def _initialize(self):
        # Why it is off matters as much as that it is off: a missing spreadsheet
        # id and a missing key file need different fixes, and "not connected"
        # alone sends the owner hunting through config for the wrong one.
        if not settings.GOOGLE_SHEETS_SPREADSHEET_ID:
            self.reason = "GOOGLE_SHEETS_SPREADSHEET_ID .env faylida ko'rsatilmagan."
            logger.info("Google Sheets: spreadsheet id yo'q. Mahalliy bazadan foydalaniladi.")
            return
        if not os.path.exists(settings.GOOGLE_SHEETS_CREDENTIALS_FILE):
            self.reason = (
                f"Kalit fayli topilmadi: {settings.GOOGLE_SHEETS_CREDENTIALS_FILE}. "
                "Google Cloud'dan service account JSON yuklab, shu nom bilan qo'ying."
            )
            logger.info("Google Sheets: credentials fayli yo'q. Mahalliy bazadan foydalaniladi.")
            return

        try:
            import gspread
            self.client = gspread.service_account(filename=settings.GOOGLE_SHEETS_CREDENTIALS_FILE)
            self.spreadsheet = self.client.open_by_key(settings.GOOGLE_SHEETS_SPREADSHEET_ID)
            self.reason = None
            logger.info("Google Sheets bilan muvaffaqiyatli ulandi.")
        except Exception as e:
            # Usually the sheet is not shared with the service account's email
            self.reason = f"Ulanishda xatolik: {e}"
            logger.warning(f"Google Sheets ga ulanishda xatolik: {e}")

    def is_connected(self) -> bool:
        return self.spreadsheet is not None

    def status(self) -> dict:
        return {"connected": self.is_connected(), "reason": self.reason}

    def fetch_products(self) -> List[Product]:
        """Fetch catalog from Google Sheets 'Products' tab"""
        products = []
        if not self.spreadsheet:
            return products

        try:
            worksheet = self.spreadsheet.worksheet("Products")
            records = worksheet.get_all_records()
            for row in records:
                p = Product(
                    id=str(row.get("ID", f"PROD-{len(products)+100}")),
                    name=str(row.get("Name", "Mahsulot")),
                    category=str(row.get("Category", "Umumiy")),
                    price=float(row.get("Price", 0)),
                    currency=str(row.get("Currency", "UZS")),
                    description=str(row.get("Description", "")),
                    image_url=str(row.get("ImageURL", "")) or None,
                    in_stock=bool(row.get("InStock", True)),
                    stock_quantity=int(row.get("StockQuantity", 10))
                )
                products.append(p)
        except Exception as e:
            logger.error(f"Google Sheets katalogini o'qishda xatolik: {e}")

        return products

    def log_order(self, order: Order) -> bool:
        """Append new order to 'Orders' sheet tab"""
        if not self.spreadsheet:
            return False

        try:
            try:
                worksheet = self.spreadsheet.worksheet("Orders")
            except Exception:
                # Create sheet if not exists
                worksheet = self.spreadsheet.add_worksheet(title="Orders", rows="1000", cols="10")
                worksheet.append_row([
                    "Order ID", "Sana", "Mijoz Ismi", "Telefon", "Telegram ID",
                    "Mahsulotlar", "Jami Summa (UZS)", "Holati", "Manzil", "Izoh"
                ])

            items_str = ", ".join([f"{item.product_name} ({item.quantity}x)" for item in order.items])
            row = [
                order.id,
                order.created_at,
                order.customer_name,
                order.customer_phone,
                order.telegram_id or "",
                items_str,
                order.total_amount,
                order.status,
                order.delivery_address or "",
                order.notes or ""
            ]
            worksheet.append_row(row)
            return True
        except Exception as e:
            logger.error(f"Google Sheets ga buyurtma yozishda xatolik: {e}")
            return False


sheets_service = GoogleSheetsService()
