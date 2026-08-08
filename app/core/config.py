import os
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent.parent
ENV_FILE = BASE_DIR / ".env"

if ENV_FILE.exists():
    load_dotenv(ENV_FILE)


class Settings:
    PORT: int = int(os.getenv("PORT", 8000))
    HOST: str = os.getenv("HOST", "0.0.0.0")
    DEBUG: bool = os.getenv("DEBUG", "True").lower() in ("true", "1", "yes")

    # Database (Postgres). Dev-default points at the local Homebrew instance.
    # Prod: override with DATABASE_URL env (e.g. postgresql+asyncpg://user:pass@host:5432/db)
    DATABASE_URL: str = os.getenv(
        "DATABASE_URL",
        "postgresql+asyncpg://ibro@localhost:5432/sotuvchi_ai",
    )

    # AI Keys
    AI_PROVIDER: str = os.getenv("AI_PROVIDER", "gemini")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")

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


settings = Settings()
