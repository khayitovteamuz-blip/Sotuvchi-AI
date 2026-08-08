from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field


class Category(BaseModel):
    id: str
    name: str
    icon: str = "📁"
    product_count: int = 0


class Product(BaseModel):
    id: str
    name: str
    category: str
    price: float
    currency: str = "UZS"
    description: str
    image_url: Optional[str] = None
    image_urls: List[str] = []
    in_stock: bool = True
    stock_quantity: int = 10


class OrderItem(BaseModel):
    product_id: str
    product_name: str
    quantity: int
    unit_price: float

    @property
    def total_price(self) -> float:
        return self.quantity * self.unit_price


class Order(BaseModel):
    id: str
    customer_name: str
    customer_phone: str
    telegram_id: Optional[str] = None
    items: List[OrderItem]
    total_amount: float
    status: str = "Yangi"  # Yangi, Tasdiqlandi, Yo'lda, Yetkazildi, Bekor qilindi
    created_at: str = Field(default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    delivery_address: Optional[str] = None
    notes: Optional[str] = None


class ChatMessage(BaseModel):
    id: str
    session_id: str
    sender: str  # user, assistant, system
    text: str
    timestamp: str = Field(default_factory=lambda: datetime.now().strftime("%H:%M:%S"))


class ChatRequest(BaseModel):
    session_id: str
    message: str
    channel: str = "web"  # web, telegram
    user_name: Optional[str] = "Mijoz"
    telegram_id: Optional[str] = None


class ChatResponse(BaseModel):
    session_id: str
    reply_text: str
    intent: str = "general_query"  # greeting, query, recommendation, order_intent, objection, closing
    recommended_products: List[Product] = []
    order_draft: Optional[Order] = None


class SystemSettings(BaseModel):
    model_config = {"protected_namespaces": ()}
    system_prompt: str
    ai_provider: str = "gemini"  # gemini, anthropic, demo
    model_name: str = "gemini-2.5-flash"
    temperature: float = 0.7
    bot_enabled: bool = True
    sheets_sync_enabled: bool = True


class DashboardStats(BaseModel):
    total_revenue: float
    total_orders: int
    active_leads: int
    conversion_rate: float
    recent_orders: List[Order]
    weekly_sales: List[float] = [2800000.0, 4200000.0, 3100000.0, 5800000.0, 4900000.0, 7200000.0, 15200000.0]
    weekly_labels: List[str] = ["Dush", "Sesh", "Chor", "Pays", "Juma", "Shan", "Yak"]
