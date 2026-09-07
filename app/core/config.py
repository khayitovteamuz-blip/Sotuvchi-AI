import os
from pathlib import Path
from typing import List

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE = BASE_DIR / ".env"

if ENV_FILE.exists():
    load_dotenv(ENV_FILE)


class Settings:
    PORT: int = int(os.getenv("PORT", 8000))
    HOST: str = os.getenv("HOST", "0.0.0.0")
    DEBUG: bool = os.getenv("DEBUG", "True").lower() in ("true", "1", "yes")

    # Worker processes. Read here as well as by the server so the app can tell
    # when it is one of several — long-polling only works in a single process.
    WEB_CONCURRENCY: int = int(os.getenv("WEB_CONCURRENCY", 1))

    # Database (Postgres). Dev-default points at the local Homebrew instance.
    # Prod: override with DATABASE_URL env (e.g. postgresql+asyncpg://user:pass@host:5432/db)
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://ibro@localhost:5432/sotuvchi_ai",
    )

    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")

    # The one model every tenant's chat runs on — no per-tenant choice, no
    # other provider. "flash" is the balanced tier: cheap and fast enough for
    # a sales turn (2+ API calls: tool round + final answer) without the
    # quality drop of "lite". Change here to move every tenant at once.
    GEMINI_CHAT_MODEL: str = os.getenv("GEMINI_CHAT_MODEL", "gemini-3.5-flash")
    # Small, cheap model: column mapping is a one-shot classification, not a
    # conversation, so the flagship model would be money spent for nothing.
    IMPORT_MAP_MODEL: str = os.getenv("IMPORT_MAP_MODEL", "gemini-3.5-flash-lite")
    # To'lov chekini o'qiydigan model. Vision kerak, lekin vazifa oddiy:
    # rasm chekmi va undagi summa qancha.
    SLIP_CHECK_MODEL: str = os.getenv("SLIP_CHECK_MODEL", "gemini-3.5-flash")

    # Telegram
    # Public base URL for inbound webhooks (Telegram). Empty on localhost — needs a
    # tunnel (ngrok/cloudflared) or a deployed domain for Telegram to reach us.
    PUBLIC_BASE_URL: str = os.getenv("PUBLIC_BASE_URL", "")

    # Long-polling mode: lets the bot work on localhost with no public URL.
    # Defaults on when PUBLIC_BASE_URL is unset; in production set a public URL
    # (and TELEGRAM_POLLING=false) so webhooks are used instead.
    TELEGRAM_POLLING: bool = os.getenv(
        "TELEGRAM_POLLING", "true" if not os.getenv("PUBLIC_BASE_URL") else "false"
    ).lower() in ("true", "1", "yes")

    # ─── AI cost ──────────────────────────────────────────────────────────────
    # Token prices in USD per 1M tokens, taken from your provider's pricing page.
    # Left at 0 the dashboard shows raw token counts and says the price is
    # unset — better than printing a confident number from a rate we guessed.
    AI_PRICE_INPUT_PER_1M: float = float(os.getenv("AI_PRICE_INPUT_PER_1M", 0) or 0)
    AI_PRICE_OUTPUT_PER_1M: float = float(os.getenv("AI_PRICE_OUTPUT_PER_1M", 0) or 0)
    USD_TO_UZS: float = float(os.getenv("USD_TO_UZS", 0) or 0)

    # Dashboard period boundaries are computed at this offset. Uzbekistan is
    # UTC+5 all year, so a fixed number beats a tz database we would have to
    # ship into the container.
    TIMEZONE_OFFSET_HOURS: int = int(os.getenv("TIMEZONE_OFFSET_HOURS", 5))

    # Extra browser origins allowed to call the API. Normally empty: the panel is
    # served by this app, so it is same-origin and needs no CORS grant at all.
    # Fill this only for a separate front-end or an embedded chat widget.
    EXTRA_CORS_ORIGINS: str = os.getenv("EXTRA_CORS_ORIGINS", "")

    # How long a chat message's raw text stays in the `messages` table before
    # scripts/retention.py deletes it. Conversations and orders are kept
    # forever regardless — only the transcript ages out. <= 0 disables it.
    MESSAGE_RETENTION_DAYS: int = int(os.getenv("MESSAGE_RETENTION_DAYS", 365))
    TELEGRAM_UPDATE_RETENTION_DAYS: int = int(
        os.getenv("TELEGRAM_UPDATE_RETENTION_DAYS", 30)
    )

    # ─── Object storage ───────────────────────────────────────────────────────
    # Uploaded product photos. Left unset, files go to the container's disk —
    # which managed hosts replace on every deploy, so the shop's pictures are
    # gone the next time we ship. Any S3-compatible service works: AWS S3,
    # Cloudflare R2, Backblaze B2, Supabase Storage.
    S3_BUCKET: str = os.getenv("S3_BUCKET", "")
    S3_ENDPOINT_URL: str = os.getenv("S3_ENDPOINT_URL", "")
    S3_ACCESS_KEY: str = os.getenv("S3_ACCESS_KEY", "")
    S3_SECRET_KEY: str = os.getenv("S3_SECRET_KEY", "")
    S3_REGION: str = os.getenv("S3_REGION", "auto")
    # The public base a browser fetches from — a CDN domain or the bucket's own
    # public URL. Without it the endpoint URL is used, which works but is slower.
    S3_PUBLIC_URL: str = os.getenv("S3_PUBLIC_URL", "")

    # Error tracking. Empty means "log to stdout and hope someone is watching",
    # which is how an outage gets reported by the customer instead of by us.
    SENTRY_DSN: str = os.getenv("SENTRY_DSN", "")
    ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development")

    # Encrypts the Telegram bot tokens at rest. Generate with:
    #   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    # Unset, tokens are stored as they always were (readable) and a warning is
    # logged — losing the key would lock every business out of its own bot.
    ENCRYPTION_KEY: str = os.getenv("ENCRYPTION_KEY", "")

    # First person, plain language — matching what the panel's placeholder
    # promises ("Masalan: Biz premium elektronika sotamiz..."). The behavior
    # rules that used to live here (stay in Uzbek, never invent a price, ask
    # for name/phone before an order) are enforced separately and unconditionally
    # by the platform-level guardrails in ai_agent.py — repeating them here as
    # a numbered list read like a technical instruction manual, not "about
    # your store", and risked drifting out of sync with the real rules.
    DEFAULT_SYSTEM_PROMPT: str = """Biz mijozlarga sifatli mahsulot va yaxshi xizmat ko'rsatishga harakat qilamiz.
Ohangimiz do'stona va samimiy — xuddi tanish sotuvchi bilan gaplashgandek.
"""

    def cors_origins(self) -> List[str]:
        """Browser origins permitted to send credentialed requests.

        Every API route requires a session cookie, so allow_origins="*" together
        with allow_credentials would have let any website on the internet drive
        the panel using a logged-in user's cookie.
        """
        origins = [o.strip() for o in self.EXTRA_CORS_ORIGINS.split(",") if o.strip()]
        if self.PUBLIC_BASE_URL:
            origins.append(self.PUBLIC_BASE_URL.rstrip("/"))
        if self.DEBUG:
            # Dev only: the panel is also opened from a phone over the LAN
            origins += [f"http://localhost:{self.PORT}", f"http://127.0.0.1:{self.PORT}"]
        return sorted(set(origins))


settings = Settings()
