"""The one model every tenant's AI runs on.

There used to be a catalogue here — three providers, per-tenant model
choice, a tariff-gated tier system. None of it was ever used by a real shop
and it tripled the tool-calling code in ai_agent.py for no product benefit.
One model, set in one place (settings.GEMINI_CHAT_MODEL), serving everyone.
"""
from importlib.util import find_spec

from app.core.config import settings

MODEL = settings.GEMINI_CHAT_MODEL

# Gemini reads voice notes and video natively; that's the whole media policy.
_MEDIA_PREFIXES = ("image/", "audio/", "video/")


def available() -> bool:
    """Whether a chat turn can actually reach the model right now."""
    if not settings.GEMINI_API_KEY:
        return False
    try:
        return find_spec("google.genai") is not None
    except (ImportError, ValueError):
        return False


def accepts_media(mime_type: str) -> bool:
    return mime_type.startswith(_MEDIA_PREFIXES)
