"""
Bilimlar bazasi hujjatlari (RAG): yuklash, bo'laklash, o'rnatish (embedding),
qidirish.

`kb_documents`/`kb_chunks` jadvallari kod yozilishidan ancha oldin bor edi,
lekin hech narsa ularni ishlatmasdi — na yuklash, na qidirish. TenantSettings
dagi qat'iy maydonlar (delivery_info, faq va h.k.) hamon birinchi manba;
bu servis ularga QO'SHIMCHA — erkin matnli hujjatlar (savol-javob ro'yxati,
uzun siyosat matni, katalog qoidalari) uchun. Qidiruv natijasi
ai_tools._search_knowledge ga qo'shiladi (o'sha qat'iy maydonlar bilan bir
qatorda), embedding chaqiruvi ishlamasa ham suhbat davom etadi — bu qatlam
ixtiyoriy, majburiy emas.
"""
import logging
import re
import uuid
from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import KbChunk, KbDocument

logger = logging.getLogger("kb_service")

# So'z/paragraf chegarasida bo'linadi. Juda kichik bo'lak konteksti kam, juda
# katta esa bitta savolga tegishsiz matnni ham qo'shib qidiruv aniqligini
# pasaytiradi.
CHUNK_CHARS = 1200
CHUNK_OVERLAP = 150

# Bitta hujjat qancha bo'lakka bo'linishi mumkin. Nazoratsiz katta matn
# (masalan PDF'dan ko'chirilgan yuzlab sahifa) minglab embedding chaqiruviga
# aylanmasin — narx va vaqt.
MAX_CHUNKS_PER_DOC = 200


def chunk_text(text: str) -> List[str]:
    """Split into overlapping chunks on paragraph boundaries where possible."""
    text = (text or "").strip()
    if not text:
        return []
    paras = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]

    chunks: List[str] = []
    buf = ""
    for p in paras:
        if buf and len(buf) + len(p) + 2 > CHUNK_CHARS:
            chunks.append(buf)
            # A short tail carries over as overlap, so a fact split across the
            # boundary isn't lost to whichever side gets retrieved.
            buf = buf[-CHUNK_OVERLAP:] + "\n\n" + p
        else:
            buf = f"{buf}\n\n{p}" if buf else p
    if buf:
        chunks.append(buf)

    # A single paragraph longer than CHUNK_CHARS (no blank-line breaks at all)
    # still needs splitting, on plain character offsets.
    out: List[str] = []
    for c in chunks:
        if len(c) <= CHUNK_CHARS * 1.5:
            out.append(c)
            continue
        for i in range(0, len(c), CHUNK_CHARS - CHUNK_OVERLAP):
            out.append(c[i:i + CHUNK_CHARS])
    return out


async def _embed(texts: List[str], task_type: str) -> List[Optional[List[float]]]:
    """Embed a batch of strings in one API call.

    Returns None per item the call could not produce — a bad batch must not
    silently drop every chunk in the document, and a chunk with no embedding
    is simply excluded from vector search rather than blocking the upload.
    """
    if not settings.GEMINI_API_KEY or not texts:
        return [None] * len(texts)
    try:
        import asyncio

        from google import genai
        from google.genai import types

        client = genai.Client(api_key=settings.GEMINI_API_KEY)
        resp = await asyncio.to_thread(
            client.models.embed_content,
            model=settings.EMBED_MODEL,
            contents=texts,
            config=types.EmbedContentConfig(
                task_type=task_type, output_dimensionality=settings.EMBED_DIM
            ),
        )
        embeddings = resp.embeddings or []
        return [e.values for e in embeddings] + [None] * (len(texts) - len(embeddings))
    except Exception as e:                     # noqa: BLE001 - a failed embed must not block the upload
        logger.warning("Embedding olinmadi: %s", e)
        return [None] * len(texts)


async def ingest_document(
    session: AsyncSession, tenant_id: str, title: str, content: str
) -> KbDocument:
    """Store a document and its embedded chunks. Chunks whose embedding
    failed are still stored (searchable later by re-embedding, not lost)."""
    doc = KbDocument(
        id=f"kbd-{uuid.uuid4().hex[:12]}",
        tenant_id=tenant_id,
        title=(title or "").strip()[:255] or "Nomsiz hujjat",
        content=content or "",
    )
    session.add(doc)

    pieces = chunk_text(content)[:MAX_CHUNKS_PER_DOC]
    vectors = await _embed(pieces, task_type="RETRIEVAL_DOCUMENT")
    for piece, vec in zip(pieces, vectors, strict=True):
        session.add(KbChunk(
            kb_document_id=doc.id, tenant_id=tenant_id, content=piece, embedding=vec,
        ))
    await session.commit()
    return doc


async def list_documents(session: AsyncSession, tenant_id: str) -> List[dict]:
    docs = (
        await session.execute(
            select(KbDocument).where(KbDocument.tenant_id == tenant_id)
            .order_by(KbDocument.created_at.desc())
        )
    ).scalars().all()
    counts = dict(
        (
            await session.execute(
                select(KbChunk.kb_document_id, func.count())
                .where(KbChunk.tenant_id == tenant_id)
                .group_by(KbChunk.kb_document_id)
            )
        ).all()
    )
    return [
        {
            "id": d.id,
            "title": d.title,
            "chars": len(d.content or ""),
            "chunks": counts.get(d.id, 0),
            "created_at": d.created_at.strftime("%Y-%m-%d %H:%M") if d.created_at else None,
        }
        for d in docs
    ]


async def delete_document(session: AsyncSession, tenant_id: str, doc_id: str) -> bool:
    doc = await session.get(KbDocument, doc_id)
    if not doc or doc.tenant_id != tenant_id:
        return False
    await session.delete(doc)  # cascades to kb_chunks (relationship + FK)
    await session.commit()
    return True


async def search(session: AsyncSession, tenant_id: str, query: str, limit: int = 3) -> List[str]:
    """Best-matching chunks for `query`, closest first.

    Empty when there is no key, no documents, or the embedding call fails —
    callers (ai_tools._search_knowledge) must have a fallback and do.
    """
    if not (query or "").strip():
        return []
    vec = (await _embed([query], task_type="RETRIEVAL_QUERY"))[0]
    if vec is None:
        return []
    rows = (
        await session.execute(
            select(KbChunk.content)
            .where(KbChunk.tenant_id == tenant_id, KbChunk.embedding.is_not(None))
            .order_by(KbChunk.embedding.cosine_distance(vec))
            .limit(limit)
        )
    ).scalars().all()
    return list(rows)
