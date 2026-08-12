"""The model catalogue the panel picks from — and whether a pick will really work.

The operator panel offers a dropdown, so the dropdown must never list a model
that would quietly fall through to the keyword engine. "Available" here means
both halves are true: the provider's SDK is importable AND its API key is set.
A provider missing either one is still listed, but marked unavailable and
refused on save, with the reason named.

Per-model flags exist because the three APIs disagree about what a request may
contain — Claude Opus 5 rejects `temperature`, Haiku 4.5 rejects `effort` — so
each entry carries what its own model accepts instead of one blended guess.
"""
from importlib.util import find_spec
from typing import Any, Dict, List, Optional, Tuple

from app.core.config import settings

PROVIDERS: Dict[str, Dict[str, Any]] = {
    "gemini": {
        "title": "Google Gemini",
        "module": "google.genai",
        "key_env": "GEMINI_API_KEY",
        # Gemini is the only provider here that reads voice notes natively.
        "media": ("image/", "audio/", "video/"),
        "models": [
            {"id": "gemini-3.5-flash-lite", "title": "Gemini 3.5 Flash Lite — eng tez, eng arzon"},
            {"id": "gemini-3.5-flash", "title": "Gemini 3.5 Flash — muvozanatli"},
            {"id": "gemini-2.5-flash", "title": "Gemini 2.5 Flash — oldingi avlod"},
            {"id": "gemini-2.5-pro", "title": "Gemini 2.5 Pro — eng kuchli, sekinroq"},
        ],
    },
    "claude": {
        "title": "Anthropic Claude",
        "module": "anthropic",
        "key_env": "ANTHROPIC_API_KEY",
        "media": ("image/",),
        "models": [
            # `adaptive` = the model takes thinking={"type":"adaptive"} + effort;
            # `temperature` = it still accepts a sampling temperature. The 5-series
            # rejects temperature outright, Haiku 4.5 rejects effort — sending the
            # wrong one is a 400, not a degraded answer.
            {"id": "claude-opus-5", "title": "Claude Opus 5 — eng kuchli",
             "adaptive": True, "temperature": False},
            {"id": "claude-sonnet-5", "title": "Claude Sonnet 5 — muvozanatli",
             "adaptive": True, "temperature": False},
            {"id": "claude-haiku-4-5", "title": "Claude Haiku 4.5 — eng tez, arzon",
             "adaptive": False, "temperature": True},
        ],
    },
    "openai": {
        "title": "OpenAI ChatGPT",
        "module": "openai",
        "key_env": "OPENAI_API_KEY",
        "media": ("image/",),
        "models": [
            {"id": "gpt-5", "title": "GPT-5 — eng kuchli", "temperature": False},
            {"id": "gpt-5-mini", "title": "GPT-5 mini — tez va arzon", "temperature": False},
            {"id": "gpt-4o-mini", "title": "GPT-4o mini — oldingi avlod", "temperature": True},
        ],
    },
}

DEFAULT_PROVIDER = "gemini"


def api_key(provider: str) -> str:
    spec = PROVIDERS.get(provider)
    return getattr(settings, spec["key_env"], "") if spec else ""


def _sdk_installed(provider: str) -> bool:
    spec = PROVIDERS.get(provider)
    if not spec:
        return False
    try:
        return find_spec(spec["module"]) is not None
    except (ImportError, ValueError):
        return False


def unavailable_reason(provider: str) -> Optional[str]:
    """Why this provider cannot answer right now — None when it can."""
    spec = PROVIDERS.get(provider)
    if not spec:
        return "Bunday provayder yo'q."
    if not api_key(provider):
        return f"{spec['title']} uchun {spec['key_env']} serverda kiritilmagan."
    if not _sdk_installed(provider):
        return f"{spec['title']} kutubxonasi ({spec['module']}) o'rnatilmagan."
    return None


def is_available(provider: str) -> bool:
    return unavailable_reason(provider) is None


def model_meta(provider: str, model_id: str) -> Optional[Dict[str, Any]]:
    for m in PROVIDERS.get(provider, {}).get("models", []):
        if m["id"] == model_id:
            return m
    return None


def accepts_media(provider: str, mime_type: str) -> bool:
    prefixes = PROVIDERS.get(provider, {}).get("media", ())
    return any(mime_type.startswith(p) for p in prefixes)


def resolve(ai_provider: Optional[str], model_name: Optional[str]) -> Optional[Tuple[str, str]]:
    """The provider+model that will actually serve this tenant, or None.

    None means every route is closed (no key, no SDK) and the caller should use
    the keyword fallback rather than pretend a model answered.
    """
    provider = (ai_provider or DEFAULT_PROVIDER).lower()
    if provider == "anthropic":       # older rows wrote the SDK's name
        provider = "claude"
    if not is_available(provider):
        return None
    # Whatever id is stored wins. The catalogue drives the dropdown, not the
    # runtime: a business already running a model we don't happen to list must
    # not be moved onto a different one behind its owner's back.
    return provider, (model_name or PROVIDERS[provider]["models"][0]["id"])


def catalog(current_provider: str = "", current_model: str = "") -> List[Dict[str, Any]]:
    """What the dropdown renders: every provider, its models, and its state.

    A model the tenant is already on but which we don't ship in the list is
    appended rather than dropped — otherwise opening the profile would silently
    re-point a working custom model at the default.
    """
    out = []
    for name, spec in PROVIDERS.items():
        models = [{"id": m["id"], "title": m["title"]} for m in spec["models"]]
        if name == (current_provider or "").lower() and current_model and \
                not any(m["id"] == current_model for m in models):
            models.append({"id": current_model, "title": f"{current_model} (hozirgi)"})
        out.append({
            "name": name,
            "title": spec["title"],
            "available": is_available(name),
            "reason": unavailable_reason(name),
            "models": models,
        })
    return out
