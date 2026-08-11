from datetime import datetime
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, ConfigDict, Field, field_validator


def _fmt_dt(v):
    """Coerce a datetime (from ORM) into the app's string format."""
    if isinstance(v, datetime):
        return v.strftime("%Y-%m-%d %H:%M:%S")
    return v


class Category(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    icon: str = "📁"
    image_url: Optional[str] = None
    product_count: int = 0


class Product(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: str
    name: str
    category: str
    price: float
    currency: str = "UZS"
    description: str = ""
    image_url: Optional[str] = None
    image_urls: List[str] = []
    in_stock: bool = True
    stock_quantity: int = 10


class OrderItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    product_id: str
    product_name: str
    quantity: int
    unit_price: float

    @property
    def total_price(self) -> float:
        return self.quantity * self.unit_price


class Order(BaseModel):
    model_config = ConfigDict(from_attributes=True)
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

    _coerce_created = field_validator("created_at", mode="before")(_fmt_dt)


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
    # Product images the agent chose to show; the channel decides how to deliver
    photos: List[Dict[str, Any]] = []


class SystemSettings(BaseModel):
    model_config = ConfigDict(from_attributes=True, protected_namespaces=())
    system_prompt: str
    ai_provider: str = "gemini"  # gemini, anthropic, demo
    model_name: str = "gemini-2.5-flash"
    temperature: float = 0.7
    bot_enabled: bool = True
    sheets_sync_enabled: bool = True
    # persona (optional in responses)
    ai_name: Optional[str] = None
    ai_tone: Optional[str] = None
    ai_language: Optional[str] = None
    greeting_message: Optional[str] = None
    auto_handoff_after: Optional[int] = None

    # Knowledge Base — the business rules the AI answers from
    delivery_info: Optional[str] = None
    delivery_fee_city: Optional[float] = None
    delivery_fee_regions: Optional[float] = None
    free_delivery_from: Optional[float] = None
    delivery_days_city: Optional[str] = None
    delivery_days_regions: Optional[str] = None
    payment_info: Optional[str] = None
    warranty_info: Optional[str] = None
    return_policy: Optional[str] = None
    working_hours: Optional[str] = None
    faq: Optional[str] = None


class DashboardStats(BaseModel):
    # AI-attributed figures come first: they are what this product delivers.
    # total_revenue is the shop's own number, kept only as context.
    ai_revenue: float = 0.0
    ai_order_count: int = 0
    total_revenue: float
    total_orders: int
    active_leads: int
    conversion_rate: float
    recent_orders: List[Order]
