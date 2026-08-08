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

    # AI Keys
    AI_PROVIDER: str = os.getenv("AI_PROVIDER", "gemini")
    GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
    ANTHROPIC_API_KEY: str = os.getenv("ANTHROPIC_API_KEY", "")

    # Telegram
    TELEGRAM_BOT_TOKEN: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_WEBHOOK_URL: str = os.getenv("TELEGRAM_WEBHOOK_URL", "")

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
