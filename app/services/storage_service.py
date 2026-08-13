"""Where uploaded pictures live.

The container's disk is not storage. Railway, Render and Fly all replace the
filesystem on every deploy, so a shop that spent an evening uploading two
hundred product photos lost them the next time we shipped a bug fix — and
nothing in the product ever said so.

Two backends, one interface:

* **S3-compatible** (AWS S3, Cloudflare R2, Backblaze B2, Supabase Storage)
  when `S3_BUCKET` is configured. This is what production should run.
* **Local disk** otherwise, so `git clone && run` still works with no cloud
  account. The panel says which one is in use, because "your images are
  temporary" is not something a business should have to discover.
"""
import logging
import uuid
from pathlib import Path
from typing import Optional, Tuple

from app.core.config import BASE_DIR, settings

logger = logging.getLogger("storage")

UPLOADS_DIR = BASE_DIR / "static" / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

_client = None
_client_failed = False


def is_remote() -> bool:
    return bool(settings.S3_BUCKET)


def _s3():
    """The boto3 client, built once. None if it cannot be built."""
    global _client, _client_failed
    if _client is not None or _client_failed:
        return _client
    try:
        import boto3
        from botocore.config import Config

        _client = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL or None,
            aws_access_key_id=settings.S3_ACCESS_KEY or None,
            aws_secret_access_key=settings.S3_SECRET_KEY or None,
            region_name=settings.S3_REGION or None,
            config=Config(signature_version="s3v4", retries={"max_attempts": 3}),
        )
    except Exception as e:
        # Falling back to the disk keeps the shop working; the log and the
        # panel's storage badge are what say the pictures are not durable.
        _client_failed = True
        logger.error(f"S3 client init failed, falling back to local disk: {e}")
    return _client


def status() -> dict:
    """What the panel shows about where files go."""
    if not is_remote():
        return {
            "backend": "local",
            "durable": False,
            "message": "Rasmlar server diskida. Qayta joylashtirilganda yo'qoladi — "
                       "S3_BUCKET sozlansa doimiy saqlanadi.",
        }
    ok = _s3() is not None
    return {
        "backend": "s3",
        "durable": ok,
        "bucket": settings.S3_BUCKET,
        "message": "Rasmlar obyekt xotirasida saqlanadi." if ok else
                   "S3 sozlangan, lekin ulanib bo'lmadi — vaqtincha disk ishlatilmoqda.",
    }


def _key(tenant_id: str, ext: str) -> str:
    return f"uploads/{tenant_id}/img_{uuid.uuid4().hex}.{ext}"


def save_image(tenant_id: str, data: bytes, ext: str, content_type: str) -> str:
    """Store the bytes and return the URL the panel and Telegram will use."""
    key = _key(tenant_id, ext)

    client = _s3() if is_remote() else None
    if client is not None:
        try:
            client.put_object(
                Bucket=settings.S3_BUCKET,
                Key=key,
                Body=data,
                ContentType=content_type,
                CacheControl="public, max-age=31536000, immutable",
            )
            base = (settings.S3_PUBLIC_URL or "").rstrip("/")
            if base:
                return f"{base}/{key}"
            return f"{settings.S3_ENDPOINT_URL.rstrip('/')}/{settings.S3_BUCKET}/{key}"
        except Exception as e:
            # A shop mid-upload should not be blocked by our bucket being down.
            logger.error(f"S3 upload failed ({key}), writing to local disk: {e}")

    path = BASE_DIR / "static" / key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return f"/static/{key}"


def local_path(url: str) -> Optional[Path]:
    """The file on our own disk this URL points at, or None if it is remote.

    The resolved path is checked against the uploads folder before anything is
    read: the value comes from a database row, and a row that ever held
    '/static/uploads/../../.env' must not become a file we hand to Telegram.
    """
    if not url or not url.startswith("/static/uploads/"):
        return None
    try:
        path = (BASE_DIR / url.lstrip("/")).resolve()
    except OSError:
        return None
    if not path.is_relative_to(UPLOADS_DIR.resolve()) or not path.is_file():
        return None
    return path


def sniff(data: bytes) -> Tuple[str, str]:
    """(mime, extension) read from the bytes themselves.

    The browser's Content-Type is a claim, not a fact — and an .svg served from
    our own origin is stored XSS against a logged-in shop owner.
    """
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", "jpg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", "png"
    if data[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif", "gif"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp", "webp"
    return "", ""
