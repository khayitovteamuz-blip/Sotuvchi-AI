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

    # AI Keys. Each provider the panel offers needs its own key here — a business
    # can only be switched to a model whose key is present, so an empty value
    # means that choice is refused with a reason rather than silently ignored.
    AI_PROVIDER: str = os.getenv("AI_PROVIDER", "gemini")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

    # Gemini models.
    # flash-lite is the default: a sales turn costs 2+ API calls (tool round +
    # final answer), and the free tier gives gemini-2.5-flash only ~5 req/min
    # versus 12+ here. Override per tenant in AI Agent → Prompt.
    GEMINI_CHAT_MODEL: str = os.getenv("GEMINI_CHAT_MODEL", "gemini-3.5-flash-lite")
    EMBED_MODEL: str = os.getenv("EMBED_MODEL", "text-embedding-004")
    EMBED_DIM: int = int(os.getenv("EMBED_DIM", 768))

    # Telegram
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_WEBHOOK_URL: str = os.getenv("TELEGRAM_WEBHOOK_URL", "")

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

    # Google Sheets
    GOOGLE_SHEETS_SPREADSHEET_ID: str = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID", "")
    GOOGLE_SHEETS_CREDENTIALS_FILE: str = os.getenv("GOOGLE_SHEETS_CREDENTIALS_FILE", "service_account.json")

    DEFAULT_SYSTEM_PROMPT: str = """Siz "Sotuvchi AI" deb nomlangan professional, samimiy va tajribali o'zbek AI sotuvchi konsulantisiz.
Sizning maqsadingiz mijozlar bilan muloqot qilish, ularning ehtiyojlarini aniqlash, mos mahsulotlarni tavsiya qilish va buyurtmani rasmiylashtirishdir.

QOIDALAR:
1. Muloqotni har doim o'zbek tilida, xushmuomala va samimiy tarzda olib boring.
2. Har bir savolga aniq, tushunarli va mahsulot afzalliklarini ko'rsatgan holda javob bering.
3. Katalogdagi mahsulotlar narxi va xususiyatlarini aniq aytib bering.
4. Mijoz xarid qilishga qiziqsa, uning ismi, telefon raqami va yetkazib berish manzilini so'rab oling.
5. Har doim muloqot oxirida mijozga qiziqarli savol yoki taklif bering (masalan: "Ushbu model sizga ma'qul keldimi? Buyurtma beramizmi?").
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
