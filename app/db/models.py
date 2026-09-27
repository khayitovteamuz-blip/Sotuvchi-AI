"""
ORM models — the full relational schema for Sotuvchi AI.

Multi-tenant rule: every business-owned row carries a `tenant_id` FK, and all
queries in the app MUST filter by the current tenant. This is what makes
"install for any business" real instead of a demo.
"""
from datetime import datetime
from typing import List, Optional

from sqlalchemy import (
    BigInteger,
    Boolean,
    Computed,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.types import TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.config import settings
from app.db.base import Base


def _now() -> datetime:
    return datetime.utcnow()


class EncryptedStr(TypeDecorator):
    """A column whose value is encrypted at rest.

    Applied at the type level on purpose: every read and write goes through it,
    so no call site can forget. Values written before encryption existed are
    returned unchanged, which is what makes the rollout gradual rather than a
    flag day — see app/core/crypto.py.
    """

    impl = String
    cache_ok = True

    def process_bind_param(self, value, dialect):
        from app.core import crypto
        return crypto.encrypt(value)

    def process_result_value(self, value, dialect):
        from app.core import crypto
        return crypto.decrypt(value)


# ─── Platform side (the operator of the service, not a customer) ──────────────
# These four tables sit deliberately outside the tenant model. A platform admin
# reads across every business, so the privilege must never be reachable from the
# `users` table a customer's own account lives in — otherwise one mass-assignment
# bug in tenant code would hand someone the whole platform.
class PlatformAdmin(Base):
    __tablename__ = "platform_admins"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_login_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


class PlatformSession(Base):
    """Separate from user_sessions on purpose: a stolen business-panel cookie
    must not open the platform panel, and vice versa."""
    __tablename__ = "platform_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    admin_id: Mapped[str] = mapped_column(
        ForeignKey("platform_admins.id", ondelete="CASCADE"), index=True
    )
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)


class PlatformAiSettings(Base):
    """The AI's behaviour rules shared by every tenant — one row, id="global".

    Split from TenantSettings on purpose: a business owner customises WHO the
    AI is (name, tone, greeting, their own shop's knowledge base) from their
    own panel, but WHAT THE AI IS ALLOWED TO DO — stay on-topic, never invent
    a price, never obey an in-chat "I'm the admin" claim — used to be a Python
    string literal in ai_agent.py. Moving it here lets the platform operator
    tune that behaviour (word a rule better, add a new guardrail) without a
    code deploy, while keeping it out of reach of any single tenant's panel.
    """
    __tablename__ = "platform_ai_settings"

    id: Mapped[str] = mapped_column(String(16), primary_key=True, default="global")
    style_text: Mapped[str] = mapped_column(Text)
    guardrails_text: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    updated_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)


class Plan(Base):
    """A tariff and the limits it actually buys.

    Limits live in a table rather than the code so raising a customer's cap is a
    click during a support call, not a deploy. NULL means unlimited.
    """
    __tablename__ = "plans"

    name: Mapped[str] = mapped_column(String(32), primary_key=True)  # start | business | pro
    title: Mapped[str] = mapped_column(String(64))
    price_uzs: Mapped[float] = mapped_column(Numeric(18, 2, asdecimal=False), default=0.0)
    max_products: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_ai_messages_monthly: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    max_operators: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    # A tariff lasts this long from the day it is bought. Data, not a constant,
    # so a promotional period needs no deploy.
    duration_days: Mapped[int] = mapped_column(Integer, default=30, server_default="30")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class Payment(Base):
    """Money ledger: every top-up request and every subscription charge.

    Kept as rows rather than a running total on the tenant so a disputed balance
    can be reconstructed — "why is my balance this number" has to be answerable.
    Positive amounts add, negative amounts spend.
    """
    __tablename__ = "payments"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), index=True
    )
    amount: Mapped[float] = mapped_column(Numeric(18, 2, asdecimal=False))
    kind: Mapped[str] = mapped_column(String(24))       # topup | subscription | adjustment
    status: Mapped[str] = mapped_column(String(16), default="pending", index=True)
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    plan_name: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_by: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)


class PlatformAuditLog(Base):
    """Who changed what, on whose account.

    A platform admin can alter any business's data, so "who raised this tenant's
    limit?" has to have an answer — including when the answer is uncomfortable.
    """
    __tablename__ = "platform_audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    admin_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # Denormalised: the log must stay readable after an admin account is deleted
    admin_email: Mapped[str] = mapped_column(String(255))
    action: Mapped[str] = mapped_column(String(64), index=True)
    tenant_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    details: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )


# ─── Tenant (the business / workspace) ────────────────────────────────────────
class Tenant(Base):
    __tablename__ = "tenants"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    business_name: Mapped[str] = mapped_column(String(255))
    # The shop's own logo — shown in its own sidebar and in /boshqaruv's
    # tenant list/profile, so a business is recognisable at a glance in both.
    logo_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    plan: Mapped[str] = mapped_column(String(32), default="start")  # start | business | pro

    # ── Owner contact ──
    # Kept on the tenant, not only on the login user: support calls the person
    # who runs the shop, and that is often not whoever holds the panel account.
    owner_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    phone: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    telegram_contact: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    contact_note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # ── Billing ──
    # Balance in UZS. Top-ups land here only after an admin confirms the
    # transfer actually arrived; a business cannot credit itself.
    balance: Mapped[float] = mapped_column(
        Numeric(18, 2, asdecimal=False), default=0.0, server_default="0"
    )
    subscription_expires_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # Suspension stops the clock rather than burning the days: the moment of
    # freezing is recorded, and on resume the expiry moves forward by exactly
    # how long the account sat idle. Unused days therefore survive.
    frozen_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # A new business starts on a trial that expires like any other period. Before
    # this existed `subscription_expires_at` was simply left empty, which made
    # every expiry check pass — a paid tariff running free for ever.
    is_trial: Mapped[bool] = mapped_column(Boolean, default=True, server_default="false")
    # Renew from the balance the day the period ends, so a shop that keeps money
    # on account never goes dark over a date it forgot.
    auto_renew: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    # Which expiry warning has already gone out (days before expiry: 7, 3, 1,
    # then 0 for "it has ended"). Kept so a reminder is sent once, not on every
    # request — expiry is evaluated lazily, many times a day.
    dunning_stage: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # Per-tenant Telegram channel (each business connects its OWN bot)
    # Encrypted at rest: a bot token is the shop's whole channel to its
    # customers, and one database dump used to hand over every business.
    telegram_bot_token: Mapped[Optional[str]] = mapped_column(EncryptedStr(512), nullable=True)
    telegram_bot_username: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    telegram_webhook_secret: Mapped[Optional[str]] = mapped_column(EncryptedStr(512), nullable=True)

    # ── Telegram Business ──
    # The bot is connected from the owner's OWN Telegram app (Settings →
    # Telegram Business → Chatbots), not from our panel — there is nothing to
    # submit here, only what Telegram tells us via a business_connection
    # update. Once set, AI replies are sent with this id so they appear to
    # come from the owner's personal account, not the bot.
    telegram_business_connection_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    # The connected account's own Telegram user id — messages the owner sends
    # themselves (from their phone) arrive on the same update stream as a
    # customer's; this is how the two are told apart.
    telegram_business_owner_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # Telegram sets is_enabled=false if the owner turns the chatbot off from
    # their Business settings without fully disconnecting it.
    telegram_business_enabled: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")

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


class TelegramUpdate(Base):
    """Durable idempotency record shared by every webhook worker."""

    __tablename__ = "telegram_updates"

    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    update_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    status: Mapped[str] = mapped_column(String(16), default="processing", index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=1, server_default="1")
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), index=True
    )
    processed_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    error: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


# ─── User (a person who logs in: owner or operator) ───────────────────────────
class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    # argon2id hashes run ~97 chars; leave room for stronger future parameters
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(32), default="owner")  # owner | operator
    full_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    tenant: Mapped["Tenant"] = relationship(back_populates="users")


# ─── Login session (one browser, one row) ─────────────────────────────────────
class UserSession(Base):
    """A logged-in browser session.

    Kept in Postgres rather than process memory: an in-memory dict drops every
    session on restart, and under two workers a request served by one process
    cannot see a token the other issued — so users get logged out at random.

    Only the SHA-256 of the cookie token is stored. The raw token lives solely
    in the user's cookie, so a leaked database yields no usable sessions.

    Named `user_sessions`, not `sessions`: Supabase's own auth stack owns
    `auth.sessions`, and two tables with one name is a trap for whoever next
    opens the dashboard.
    """
    __tablename__ = "user_sessions"

    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    # Indexed because the expired-row sweep filters on it
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    ip: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    user_agent: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)


# ─── Login throttling ─────────────────────────────────────────────────────────
class LoginAttempt(Base):
    """Failed-login counter, keyed by "ip|email".

    Shared state, not per-process counters: with N workers an in-memory tally
    lets an attacker make N times the intended attempts, and a restart wipes a
    lockout entirely.
    """
    __tablename__ = "login_attempts"

    key: Mapped[str] = mapped_column(String(255), primary_key=True)
    fail_count: Mapped[int] = mapped_column(Integer, default=0)
    # Start of the rolling window the failures are counted in
    window_start: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    locked_until: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)


# ─── Per-tenant AI / system settings ──────────────────────────────────────────
class TenantSettings(Base):
    __tablename__ = "tenant_settings"

    tenant_id: Mapped[str] = mapped_column(
        ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True
    )
    system_prompt: Mapped[str] = mapped_column(Text, default=settings.DEFAULT_SYSTEM_PROMPT)
    temperature: Mapped[float] = mapped_column(Float, default=0.7)
    bot_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    sheets_sync_enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # Owner pastes a normal share link; we convert it to the sheet's CSV export
    # URL ourselves — no Google API credentials, no OAuth, just "anyone with
    # the link can view". Only ever written by the sync endpoint itself, after
    # a fetch has proven the link actually works — never by the generic
    # settings save, which would let a bad link overwrite a working one.
    google_sheet_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    google_sheet_synced_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    google_sheet_product_count: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

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
    delivery_fee_city: Mapped[Optional[float]] = mapped_column(
        Numeric(18, 2, asdecimal=False), nullable=True
    )
    delivery_fee_regions: Mapped[Optional[float]] = mapped_column(
        Numeric(18, 2, asdecimal=False), nullable=True
    )
    free_delivery_from: Mapped[Optional[float]] = mapped_column(
        Numeric(18, 2, asdecimal=False), nullable=True
    )
    delivery_days_city: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    delivery_days_regions: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    payment_info: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    warranty_info: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    return_policy: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    working_hours: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    faq: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    # The number a customer is given when no human can pick the chat up.
    # Deliberately NOT Tenant.phone: that one is the owner's own line, kept for
    # the platform's support team, and is edited from /boshqaruv — reusing it
    # would mean a platform admin silently changing what customers are told.
    contact_phone: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Where operator alerts are delivered. The owner pairs their own Telegram by
    # sending "/operator <pairing_code>" to the bot — without this, a handoff
    # only shows in the panel and nobody is actually notified.
    operator_chat_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    operator_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    pairing_code: Mapped[Optional[str]] = mapped_column(String(16), nullable=True)

    # Which alerts go where: {"order": ["-1001234"], "handoff": ["555", "-100999"]}
    # A list because one event can legitimately reach two places — an escalation
    # should ping the owner *and* the operators' group. An event missing from the
    # map is not sent at all, which is how a shop switches one off.
    notify_routes: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)


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
    price: Mapped[float] = mapped_column(Numeric(18, 2, asdecimal=False), default=0.0)
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


# ─── Notification routing ─────────────────────────────────────────────────────
class NotifyChannel(Base):
    """One Telegram destination this business has connected.

    Before this table there were four fixed columns on the tenant — an operator
    chat and three named groups — so every alert the owner cared about landed in
    the same personal chat: orders, escalations and subscription warnings all
    mixed together. A destination is now just a paired chat; which alerts reach
    it is a separate question, answered by `TenantSettings.notify_routes`.

    A Telegram *channel* is a valid destination and often the right one: it is
    one-way, so a stream of order alerts never turns into a conversation.
    """

    __tablename__ = "notify_channels"
    __table_args__ = (
        UniqueConstraint("tenant_id", "chat_id", name="uq_notify_channel_tenant_chat"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    chat_id: Mapped[str] = mapped_column(String(64))
    # private | group | channel — shown in the panel, and used to keep the
    # order-confirmation buttons out of places where nobody can press them.
    kind: Mapped[str] = mapped_column(String(16), default="private")
    title: Mapped[str] = mapped_column(String(255), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


# ─── Customer (the person, not the conversation) ──────────────────────────────
class Customer(Base):
    """One human being, however many chats and orders they leave behind.

    Before this existed the customer lived denormalised in three places — on the
    conversation, on the order, and in a GROUP BY that ran at report time — so
    the same person writing from two channels was two different "customers" and
    nobody could answer "what has this one bought before?".

    Identity is resolved two ways, which is why `CustomerIdentity` is separate:
    by channel handle (a Telegram chat id is known from the first hello) and by
    phone number (known only once they order). The phone is the stronger key and
    is what links a Telegram chat to a web chat from the same person.
    """

    __tablename__ = "customers"
    __table_args__ = (
        # Partial: a lead who has not given a phone yet must not collide with
        # every other phone-less lead on a single empty-string key.
        Index("uq_customer_tenant_phone", "tenant_id", "phone",
              unique=True, postgresql_where=text("phone IS NOT NULL")),
        Index("ix_customers_tenant_seen", "tenant_id", "last_seen_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    # Stored normalised (+998XXXXXXXXX) so "+998 90 123 45 67", "998901234567"
    # and "901234567" are one customer rather than three.
    phone: Mapped[Optional[str]] = mapped_column(String(32), nullable=True)
    telegram_username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Kept as columns rather than counted on every read: the customer list is
    # sorted by them, and a sort over a live aggregate of every order does not
    # survive a catalogue that grows.
    orders_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    total_spent: Mapped[float] = mapped_column(
        Numeric(18, 2, asdecimal=False), default=0.0, server_default="0"
    )

    # What the shop knows that the system does not: "prefers evening delivery".
    note: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    identities: Mapped[List["CustomerIdentity"]] = relationship(
        back_populates="customer", cascade="all, delete-orphan", lazy="selectin"
    )


class CustomerIdentity(Base):
    """One handle a customer is reachable by — a Telegram chat, a web session."""

    __tablename__ = "customer_identities"
    __table_args__ = (
        UniqueConstraint("tenant_id", "channel", "external_id", name="uq_identity_tenant_channel_ext"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    customer_id: Mapped[str] = mapped_column(
        ForeignKey("customers.id", ondelete="CASCADE"), index=True
    )
    channel: Mapped[str] = mapped_column(String(16))
    external_id: Mapped[str] = mapped_column(String(128))

    customer: Mapped["Customer"] = relationship(back_populates="identities")


# ─── Orders ───────────────────────────────────────────────────────────────────
class Order(Base):
    __tablename__ = "orders"
    __table_args__ = (
        Index(
            "uq_orders_tenant_source_update",
            "tenant_id",
            "source_update_id",
            unique=True,
            postgresql_where=text("source_update_id IS NOT NULL"),
        ),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id", ondelete="CASCADE"), index=True)
    # Denormalised on purpose: an order is a record of what was agreed that
    # day, so it keeps the name and number given then even if the customer
    # later changes theirs. customer_id is the link for "what else did they buy".
    customer_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    customer_name: Mapped[str] = mapped_column(String(255))
    customer_phone: Mapped[str] = mapped_column(String(64))
    telegram_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    conversation_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True, index=True)
    # Telegram retries must resolve to the same order, never a second sale.
    source_update_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    total_amount: Mapped[float] = mapped_column(Numeric(18, 2, asdecimal=False), default=0.0)
    status: Mapped[str] = mapped_column(String(32), default="Yangi")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    delivery_address: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    notes: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # Customer's pinned location, when they share one in the chat
    latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Payment slip the customer photographed — the team confirms against this
    payment_photo_file_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    # Telegram handle/id, so the team can reach the customer from the receipt
    customer_username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

    # Team confirmation from the orders group — first tap wins, and we keep who
    confirmed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_by: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    receipt_message_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # Which chat the receipt was posted to. Once destinations became routable
    # this stopped being derivable from a fixed column — editing the message
    # after confirmation needs the chat it actually went to.
    receipt_chat_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)

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
    unit_price: Mapped[float] = mapped_column(Numeric(18, 2, asdecimal=False), default=0.0)

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
    customer_id: Mapped[Optional[str]] = mapped_column(
        ForeignKey("customers.id", ondelete="SET NULL"), nullable=True, index=True
    )
    customer_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    customer_phone: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # Last map pin the customer shared — copied onto the order when one is placed
    last_latitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    last_longitude: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    # Last photo the customer sent (payment slip). Telegram file_id, so the bot
    # can forward it to the team without re-uploading the image.
    last_photo_file_id: Mapped[Optional[str]] = mapped_column(String(256), nullable=True)
    customer_username: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    # Set when this conversation arrived via Telegram Business (a business_message
    # update), so a later reply — AI or a human's from the Inbox — knows to send
    # with this id and appear as the owner's own account. Null for a chat that
    # only ever talked to the bot directly.
    telegram_business_connection_id: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="ai")  # ai | operator | closed
    assigned_user_id: Mapped[Optional[str]] = mapped_column(String(64), nullable=True)
    assigned_user_name: Mapped[Optional[str]] = mapped_column(String(128), nullable=True)
    handoff_reason: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    fail_streak: Mapped[int] = mapped_column(Integer, default=0)  # consecutive "don't know" -> auto handoff
    # Ketma-ket mavzudan tashqari xabarlar soni. 2 va undan ko'p bo'lsa AI shu
    # xabarga javob yubormaydi (lekin Inboxda ko'rinadi) — chat yopilmaydi,
    # bloklanmaydi, mijoz mavzuga qaytishi bilan darhol nolga tushadi. abuse_count
    # dan farqli o'laroq bu doimiy jazo emas, faqat bir marta jim turish.
    off_topic_streak: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # Haqoratli xabarlar soni. 1 -> ogohlantirildi, 2+ -> bloklangan.
    # Suhbatda turadi, mijozda emas: blok shu kanaldagi shu chatga tegishli,
    # va operator uni panelda bir bosishda bekor qila oladi.
    abuse_count: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    blocked_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    unread_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_message_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    messages: Mapped[List["Message"]] = relationship(
        back_populates="conversation", cascade="all, delete-orphan"
    )


class Message(Base):
    __tablename__ = "messages"
    __table_args__ = (
        # Every dashboard figure is "this tenant, this period". Declared here as
        # well as in migration b3f7a91c204e so autogenerate stops proposing to
        # drop an index the queries depend on.
        Index("ix_messages_tenant_created", "tenant_id", "created_at"),
    )

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
    # Split out because input and output are billed at different rates — the
    # blended total cannot be turned into money.
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    output_tokens: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)  # response-time metric
    meta: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)  # tool_calls, retrieved docs, etc.
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    conversation: Mapped["Conversation"] = relationship(back_populates="messages")
