"""
ORM models — the full relational schema for Sotuvchi AI.

Multi-tenant rule: every business-owned row carries a `tenant_id` FK, and all
queries in the app MUST filter by the current tenant. This is what makes
"install for any business" real instead of a demo.
"""
from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    Boolean,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship
from pgvector.sqlalchemy import Vector

from app.core.config import settings
from app.db.base import Base


def _now() -> datetime:
    return datetime.utcnow()


# ─── Tenant (the business / workspace) ────────────────────────────────────────
class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    business_name: Mapped[str] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    plan: Mapped[str] = mapped_column(String(32), default="start")  # start | business | pro

    # Per-tenant Telegram channel (each business connects its OWN bot)
    telegram_bot_token: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    telegram_bot_username: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    telegram_webhook_secret: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # ── Team groups ──
    # Chat ids, not invite links: an invite link (t.me/+hash) carries no chat_id,
    # so the bot must be added to the group and paired from inside it.
    orders_group_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    orders_group_title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    work_group_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    work_group_title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    operators_group_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    operators_group_title: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    group_pairing_code: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)

    users: Mapped[List["User"]] = relationship(back_populates="tenant", cascade="all, delete-orphan")


# ─── User (a person who logs in: owner or operator) ───────────────────────────
class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(32), default="owner")  # owner | operator
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    tenant: Mapped["Tenant"] = relationship(back_populates="users")


# ─── Per-tenant AI / system settings ──────────────────────────────────────────
class TenantSettings(Base):
    __tablename__ = "tenant_settings"

    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    system_prompt: Mapped[str] = mapped_column(Text, default=settings.DEFAULT_SYSTEM_PROMPT)
    ai_provider: Mapped[str] = mapped_column(String(32), default="gemini")
    model_name: Mapped[str] = mapped_column(String(64), default=settings.GEMINI_CHAT_MODEL)
    temperature: Mapped[float] = mapped_column(Float, default=0.7)
    bot_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sheets_sync_enabled: Mapped[bool] = mapped_column(Boolean, default=True)

    # AI persona (AI Agent → Persona tab)
    ai_name: Mapped[str] = mapped_column(String(64), default="Sotuvchi AI")
    ai_tone: Mapped[str] = mapped_column(String(32), default="professional")  # professional|friendly|concise
    ai_language: Mapped[str] = mapped_column(String(8), default="uz")  # uz|ru|en
    greeting_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Guardrail: escalate to a human after N consecutive "I don't know" turns
    auto_handoff_after: Mapped[int] = mapped_column(Integer, default=3)

    # ── Knowledge Base: the business rules the AI answers from ──
    # Structured fields, not free text, because delivery cost must be a number
    # the calc_delivery tool can use — not a sentence the model interprets.
    delivery_info: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    delivery_fee_city: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    delivery_fee_regions: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    free_delivery_from: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    delivery_days_city: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    delivery_days_regions: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    payment_info: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    warranty_info: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    return_policy: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    working_hours: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    faq: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Where operator alerts are delivered. The owner pairs their own Telegram by
    # sending "/operator <pairing_code>" to the bot — without this, a handoff
    # only shows in the panel and nobody is actually notified.
    operator_chat_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    operator_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    pairing_code: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)
    notify_on_handoff: Mapped[bool] = mapped_column(Boolean, default=True)
    notify_on_order: Mapped[bool] = mapped_column(Boolean, default=True)


# ─── Catalog ──────────────────────────────────────────────────────────────────
class Category(Base):
    __tablename__ = "categories"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(128))
    icon: Mapped[str] = mapped_column(String(16), default="📁")
    image_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


class Product(Base):
    __tablename__ = "products"

    # Composite PK: product ids (e.g. PROD-101) are only unique WITHIN a tenant,
    # so the tenant_id is part of the key. Nothing FKs to products (order_items
    # keep a denormalised product snapshot), so this stays clean.
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True, index=True
    )
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(128), default="")
    price: Mapped[float] = mapped_column(Float, default=0.0)
    currency: Mapped[str] = mapped_column(String(8), default="UZS")
    description: Mapped[str] = mapped_column(Text, default="")
    image_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    image_urls: Mapped[list] = mapped_column(JSONB, default=list)
    in_stock: Mapped[bool] = mapped_column(Boolean, default=True)
    stock_quantity: Mapped[int] = mapped_column(Integer, default=10)
    sku: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Postgres maintains this (see migration 214e5f10a29f) and the trigram search
    # runs against it. Declared here so autogenerate knows it belongs — left out,
    # Alembic reads it as a stray column and writes a DROP into the next migration.
    search_text: Mapped[Optional[str]] = mapped_column(
        Text,
        Computed(
            "sotuvchi_norm(coalesce(name,'') || ' ' || coalesce(category,'') || ' ' || coalesce(description,''))",
            persisted=True,
        ),
        nullable=True,
    )


# ─── Orders ───────────────────────────────────────────────────────────────────
class Order(Base):
    __tablename__ = "orders"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    customer_name: Mapped[str] = mapped_column(String(255))
    customer_phone: Mapped[str] = mapped_column(String(64))
    telegram_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    conversation_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    total_amount: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(32), default="Yangi")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    delivery_address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Customer's pinned location, when they share one in the chat
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Payment slip the customer photographed — the team confirms against this
    payment_photo_file_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)

    # Team confirmation from the orders group — first tap wins, and we keep who
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    receipt_message_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    items: Mapped[List["OrderItem"]] = relationship(
        back_populates="order", cascade="all, delete-orphan", lazy="selectin"
    )


class OrderItem(Base):
    __tablename__ = "order_items"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    order_id: Mapped[str] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    product_id: Mapped[str] = mapped_column(String(64))
    product_name: Mapped[str] = mapped_column(String(255))
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    unit_price: Mapped[float] = mapped_column(Float, default=0.0)

    order: Mapped["Order"] = relationship(back_populates="items")


# ─── Conversations & Messages (the Inbox backbone) ────────────────────────────
class Conversation(Base):
    __tablename__ = "conversations"
    __table_args__ = (
        UniqueConstraint("tenant_id", "channel", "external_id", name="uq_conv_tenant_channel_ext"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    channel: Mapped[str] = mapped_column(String(16), default="web")  # web | telegram | instagram
    external_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True, index=True)
    customer_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    customer_phone: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # Last map pin the customer shared — copied onto the order when one is placed
    last_latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    last_longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Last photo the customer sent (payment slip). Telegram file_id, so the bot
    # can forward it to the team without re-uploading the image.
    last_photo_file_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="ai")  # ai | operator | closed
    assigned_user_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    assigned_user_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    handoff_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    fail_streak: Mapped[int] = mapped_column(Integer, default=0)  # consecutive "don't know" -> auto handoff
    unread_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_message_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    messages: Mapped[List["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[str] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    sender: Mapped[str] = mapped_column(String(16))  # user | assistant | operator | system
    text: Mapped[str] = mapped_column(Text)
    intent: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    model_name: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    tokens: Mapped[int] = mapped_column(Integer, default=0)  # token cost tracking (billing/metrics)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)  # response-time metric
    meta: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)  # tool_calls, retrieved docs, etc.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")


# ─── Knowledge Base (RAG via pgvector) ────────────────────────────────────────
class KbDocument(Base):
    __tablename__ = "kb_documents"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    chunks: Mapped[List["KbChunk"]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class KbChunk(Base):
    __tablename__ = "kb_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kb_document_id: Mapped[str] = mapped_column(
        ForeignKey("kb_documents.id", ondelete="CASCADE"), index=True
    )
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    content: Mapped[str] = mapped_column(Text)
    embedding: Mapped[Optional[list]] = mapped_column(Vector(settings.EMBED_DIM), nullable=True)

    document: Mapped["KbDocument"] = relationship(back_populates="chunks")
