"""
Async SQLAlchemy engine + session factory.

The DB engine is a connection-string swap:
  dev  -> postgresql+asyncpg://ibro@localhost:5432/sotuvchi_ai
  prod -> set DATABASE_URL env

Everything the app does goes through an AsyncSession scoped to a request.
"""
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    AsyncAttrs,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.core.config import settings


class Base(AsyncAttrs, DeclarativeBase):
    """Declarative base for all ORM models."""
    pass


# Supabase session-mode pooler caps the *project* at 15 client connections,
# and that budget is shared by every process that dials in: the web server,
# a second server someone left running, a migration, a psql shell.
#
# With pool_size=5 + max_overflow=5 a single process could take 10 of those 15.
# Two processes then exhausted the pool and Postgres answered
#   (EMAXCONNSESSION) max clients reached in session mode
# on *login*, so the panel rendered empty with no JS error — a failure that
# looks like broken markup and costs an hour to trace back here.
#
# 3 + 2 keeps one process under 5 connections, so three can run side by side
# and still fit. Raise these only together with the Supabase plan limit.
POOL_SIZE = 3
MAX_OVERFLOW = 2

# pool_pre_ping o'chirilgan. U har bir sessiya boshida bazaga qo'shimcha
# "select 1" yuboradi — bir borish-kelish. Baza Frankfurtda, shuning uchun
# bitta borish-kelish ~90 ms, va o'lchov bo'yicha pre_ping har bir so'rovga
# ~293 ms qo'shardi (565 ms -> 273 ms uni o'chirgach). Kunlik ishlatishda bu
# panelning har bir bosishida seziladigan kechikish edi.
#
# O'rniga pool_recycle qisqartirildi: ulanish Supabase pooleri uni yopishidan
# ancha oldin yangilanadi, ya'ni "o'lik ulanish" holati amalda yuzaga
# kelmaydi. Pre_ping esa uni har safar tekshirib, sog'lom ulanishlar uchun
# ham to'lov olardi.
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_pre_ping=False,
    pool_size=POOL_SIZE,
    max_overflow=MAX_OVERFLOW,
    # Wait briefly for a free connection instead of hanging the request. The
    # caller gets TimeoutError, which surfaces as a clean 500 rather than a
    # request that never returns.
    pool_timeout=10,
    # Supabase drops idle connections; recycling before that avoids handing
    # out a socket the server has already closed. 5 daqiqa — pooler chidamidan
    # xiyla qisqa, pre_ping o'rnini shu bosadi.
    pool_recycle=300,
)

AsyncSessionLocal = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,   # keep attributes usable after commit
    autoflush=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields a request-scoped AsyncSession."""
    async with AsyncSessionLocal() as session:
        yield session
