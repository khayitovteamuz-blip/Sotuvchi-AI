import json
from pathlib import Path
from typing import List, Dict, Optional, Any
from app.models.schema import Product, Order, ChatMessage, SystemSettings, Category
from app.core.config import settings, BASE_DIR

# Legacy global data dir (used only for backward compat / migration)
DATA_DIR = BASE_DIR / "data"
DATA_DIR.mkdir(exist_ok=True)


# Default Initial Demo Products
DEFAULT_PRODUCTS = [
    Product(
        id="PROD-101",
        name="iPhone 15 Pro Max 256GB",
        category="Smartfonlar",
        price=15200000.0,
        currency="UZS",
        description="Titan korpus, A17 Pro chip, 48MP kamera va uzoq vaqt quvvat ushlovchi batareya.",
        image_url="https://images.unsplash.com/photo-1695048133142-1a20484d2569?w=600&auto=format&fit=crop&q=80",
        image_urls=["https://images.unsplash.com/photo-1695048133142-1a20484d2569?w=600&auto=format&fit=crop&q=80"],
        in_stock=True,
        stock_quantity=8
    ),
    Product(
        id="PROD-102",
        name="MacBook Air M3 15-inch 16/512GB",
        category="Noutbuklar",
        price=18900000.0,
        currency="UZS",
        description="Juda yengil, M3 protsessor, 18 soat batareya ishlash muddati, Liquid Retina displey.",
        image_url="https://images.unsplash.com/photo-1517336714731-489689fd1ca8?w=600&auto=format&fit=crop&q=80",
        image_urls=["https://images.unsplash.com/photo-1517336714731-489689fd1ca8?w=600&auto=format&fit=crop&q=80"],
        in_stock=True,
        stock_quantity=5
    ),
    Product(
        id="PROD-103",
        name="AirPods Pro 2 (USB-C)",
        category="Aksessuarlar",
        price=2950000.0,
        currency="UZS",
        description="Faol shovqinni bekor qilish (ANC), Shaffoflik rejimi, MagSafe qutisi va kristal toza ovoz.",
        image_url="https://images.unsplash.com/photo-1600294037681-c80b4cb5b434?w=600&auto=format&fit=crop&q=80",
        image_urls=["https://images.unsplash.com/photo-1600294037681-c80b4cb5b434?w=600&auto=format&fit=crop&q=80"],
        in_stock=True,
        stock_quantity=15
    ),
    Product(
        id="PROD-104",
        name="Apple Watch Series 9 GPS 45mm",
        category="Aqlli soatlar",
        price=5400000.0,
        currency="UZS",
        description="Double Tap imo-ishorasi, yorqinroq displey, salomatlik va sport funksiyalari.",
        image_url="https://images.unsplash.com/photo-1508685096489-7aacd43bd3b1?w=600&auto=format&fit=crop&q=80",
        image_urls=["https://images.unsplash.com/photo-1508685096489-7aacd43bd3b1?w=600&auto=format&fit=crop&q=80"],
        in_stock=True,
        stock_quantity=10
    )
]

DEFAULT_CATEGORIES = [
    Category(id="cat-1", name="Smartfonlar", icon="📱",
             image_url="https://images.unsplash.com/photo-1511707171634-5f897ff02aa9?w=300&auto=format&fit=crop&q=80",
             product_count=1),
    Category(id="cat-2", name="Noutbuklar", icon="💻",
             image_url="https://images.unsplash.com/photo-1517336714731-489689fd1ca8?w=300&auto=format&fit=crop&q=80",
             product_count=1),
    Category(id="cat-3", name="Aksessuarlar", icon="🎧",
             image_url="https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=300&auto=format&fit=crop&q=80",
             product_count=1),
    Category(id="cat-4", name="Aqlli soatlar", icon="⌚️",
             image_url="https://images.unsplash.com/photo-1508685096489-7aacd43bd3b1?w=300&auto=format&fit=crop&q=80",
             product_count=1),
]


class Database:
    """
    Per-tenant database.
    Pass tenant_data_dir to use a tenant-isolated data directory.
    Falls back to legacy DATA_DIR if not specified.
    """
    def __init__(self, tenant_data_dir: Optional[Path] = None):
        data_dir = tenant_data_dir or DATA_DIR
        data_dir.mkdir(parents=True, exist_ok=True)

        self._products_file = data_dir / "products.json"
        self._orders_file = data_dir / "orders.json"
        self._settings_file = data_dir / "settings.json"
        self._categories_file = data_dir / "categories.json"

        self.products: Dict[str, Product] = {}
        self.orders: List[Order] = []
        self.chat_history: Dict[str, List[ChatMessage]] = {}
        self.settings: SystemSettings = SystemSettings(
            system_prompt=settings.DEFAULT_SYSTEM_PROMPT,
            ai_provider=settings.AI_PROVIDER,
            model_name="gemini-2.5-flash"
        )
        self.categories: List[Category] = [c.model_copy() for c in DEFAULT_CATEGORIES]
        self._load_data()

    # ─── Categories ──────────────────────────────────────────────────────────
    def get_categories(self) -> List[Category]:
        for cat in self.categories:
            cat.product_count = sum(
                1 for p in self.products.values()
                if p.category.lower() == cat.name.lower()
            )
        return self.categories

    def add_category(self, category: Category) -> Category:
        self.categories.append(category)
        self._save_categories()
        return category

    def update_category(self, category_id: str, category: Category) -> Optional[Category]:
        for i, c in enumerate(self.categories):
            if c.id == category_id:
                old_name = c.name
                self.categories[i] = category
                if old_name.lower() != category.name.lower():
                    for p in self.products.values():
                        if p.category.lower() == old_name.lower():
                            p.category = category.name
                    self.save_products()
                self._save_categories()
                return category
        return None

    def delete_category(self, category_id: str) -> bool:
        old_len = len(self.categories)
        self.categories = [c for c in self.categories if c.id != category_id]
        if len(self.categories) < old_len:
            self._save_categories()
            return True
        return False

    def _save_categories(self):
        with open(self._categories_file, "w", encoding="utf-8") as f:
            json.dump([c.model_dump() for c in self.categories], f, ensure_ascii=False, indent=2)

    # ─── Persistence ─────────────────────────────────────────────────────────
    def _load_data(self):
        # Products
        if self._products_file.exists():
            try:
                with open(self._products_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for item in data:
                        p = Product(**item)
                        self.products[p.id] = p
            except Exception:
                self._load_default_products()
        else:
            self._load_default_products()

        # Categories
        if self._categories_file.exists():
            try:
                with open(self._categories_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.categories = [Category(**item) for item in data]
            except Exception:
                pass  # use DEFAULT_CATEGORIES already set in __init__

        # Orders
        if self._orders_file.exists():
            try:
                with open(self._orders_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.orders = [Order(**item) for item in data]
            except Exception:
                self.orders = []

        # Settings
        if self._settings_file.exists():
            try:
                with open(self._settings_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.settings = SystemSettings(**data)
            except Exception:
                pass

    def _load_default_products(self):
        self.products = {p.id: p for p in DEFAULT_PRODUCTS}
        self.save_products()

    def save_products(self):
        with open(self._products_file, "w", encoding="utf-8") as f:
            json.dump([p.model_dump() for p in self.products.values()], f, ensure_ascii=False, indent=2)

    def save_orders(self):
        with open(self._orders_file, "w", encoding="utf-8") as f:
            json.dump([o.model_dump() for o in self.orders], f, ensure_ascii=False, indent=2)

    def save_settings(self):
        with open(self._settings_file, "w", encoding="utf-8") as f:
            json.dump(self.settings.model_dump(), f, ensure_ascii=False, indent=2)

    # ─── Products CRUD ───────────────────────────────────────────────────────
    def get_products(self) -> List[Product]:
        return list(self.products.values())

    def get_product(self, product_id: str) -> Optional[Product]:
        return self.products.get(product_id)

    def add_product(self, product: Product) -> Product:
        self.products[product.id] = product
        self.save_products()
        return product

    def update_product(self, product_id: str, product: Product) -> Optional[Product]:
        if product_id in self.products:
            self.products[product_id] = product
            self.save_products()
            return product
        return None

    def delete_product(self, product_id: str) -> bool:
        if product_id in self.products:
            del self.products[product_id]
            self.save_products()
            return True
        return False

    # ─── Orders CRUD ─────────────────────────────────────────────────────────
    def get_orders(self) -> List[Order]:
        return sorted(self.orders, key=lambda x: x.created_at, reverse=True)

    def add_order(self, order: Order) -> Order:
        self.orders.append(order)
        self.save_orders()
        return order

    def update_order_status(self, order_id: str, status: str) -> Optional[Order]:
        for o in self.orders:
            if o.id == order_id:
                o.status = status
                self.save_orders()
                return o
        return None

    # ─── Chat Sessions ───────────────────────────────────────────────────────
    def get_session_history(self, session_id: str) -> List[ChatMessage]:
        return self.chat_history.get(session_id, [])

    def add_chat_message(self, message: ChatMessage):
        if message.session_id not in self.chat_history:
            self.chat_history[message.session_id] = []
        self.chat_history[message.session_id].append(message)


# Legacy singleton — kept for chat_api and bot compatibility (not tenant-aware)
db = Database()
