"""
Sotuvchi AI — application entry point.

`app` is built at module level so a process manager can import it as `main:app`
and fork several workers. Running uvicorn from inside this file is a development
convenience only; the container CMD drives the server directly, which is what
makes multiple workers possible.
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import text

from app.api.admin_api import router as admin_router
from app.api.auth_api import router as auth_router
from app.api.bot_webhook import router as bot_router
from app.api.chat_api import router as chat_router
from app.api.inbox_api import router as inbox_router
from app.api.integrations_api import router as integrations_router
from app.api.platform_api import auth_router as platform_auth_router
from app.api.platform_api import router as platform_router
from app.api.users_api import router as users_router
from app.core.config import settings
from app.db.base import AsyncSessionLocal, engine
from app.services.telegram_poller import telegram_poller

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"
TEMPLATES_DIR = BASE_DIR / "templates"


def _polling_allowed() -> bool:
    """Long-polling may run in exactly one process.

    Each worker would open its own getUpdates loop and Telegram would hand the
    same update to every one of them, so the customer receives N identical
    replies. Webhooks have no such limit, which is what production uses.
    """
    if not settings.TELEGRAM_POLLING:
        return False
    if settings.WEB_CONCURRENCY > 1:
        logger.error(
            "TELEGRAM_POLLING yoqilgan, lekin WEB_CONCURRENCY=%d. Polling ishga "
            "tushirilmadi: har bir worker bir xil xabarni qayta ishlab, mijozga "
            "takroriy javob yuborardi. Ishlab chiqarishda PUBLIC_BASE_URL ni "
            "qo'ying va webhook rejimiga o'ting.",
            settings.WEB_CONCURRENCY,
        )
        return False
    return True


@asynccontextmanager
async def lifespan(app: FastAPI):
    polling = _polling_allowed()
    if polling:
        await telegram_poller.start()
    yield
    if polling:
        await telegram_poller.stop()
    # Return pooled connections before the process exits, so a redeploy does
    # not leave sockets open against Postgres until they time out.
    await engine.dispose()


app = FastAPI(
    title="Sotuvchi AI",
    description="O'zbek tilidagi AI sotuvchi agenti — Telegram bot va boshqaruv paneli.",
    version="2.1.0",
    lifespan=lifespan,
    # The schema names every endpoint and its payloads; there is no reason to
    # publish that from a production host.
    docs_url="/docs" if settings.DEBUG else None,
    redoc_url="/redoc" if settings.DEBUG else None,
    openapi_url="/openapi.json" if settings.DEBUG else None,
)

# CORS. The dashboard is served by this app, so it is same-origin and this list
# is normally empty — cross-origin callers are simply refused.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Content-Type"],
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    """Headers a browser needs before it will defend the panel for us.

    Without them the panel can be framed by another site (clickjacking against
    a logged-in shop owner), and an uploaded file that slips past validation
    can still be sniffed into something executable.
    """
    response = await call_next(request)
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "same-origin"
    # The panels load only their own assets — no CDN, no external fonts — so a
    # strict policy costs nothing here. 'unsafe-inline' stays because the
    # templates still carry inline styles and onclick handlers.
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "img-src 'self' data: https:; "
        "script-src 'self' 'unsafe-inline'; "
        "style-src 'self' 'unsafe-inline'; "
        "connect-src 'self'; "
        "frame-ancestors 'none'; "
        "base-uri 'self'; "
        "form-action 'self'"
    )
    if settings.PUBLIC_BASE_URL.startswith("https://"):
        response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
    return response

STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")
templates = Jinja2Templates(directory=str(TEMPLATES_DIR))

app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(admin_router)
app.include_router(bot_router)
app.include_router(inbox_router)
app.include_router(integrations_router)
app.include_router(platform_auth_router)
app.include_router(platform_router)
app.include_router(users_router)


def _asset_version() -> str:
    """Cache-buster derived from the assets themselves.

    A hand-written ?v=3.0 goes stale the moment the file changes again, and the
    browser then serves old JS against new HTML — which looks like broken
    features, not a caching bug. Deriving it from mtimes makes that impossible.
    """
    stamp = 0.0
    for rel in ("js/app.js", "css/style.css", "js/platform.js", "css/platform.css"):
        f = STATIC_DIR / rel
        if f.exists():
            stamp = max(stamp, f.stat().st_mtime)
    return str(int(stamp))


@app.get("/", include_in_schema=False)
async def root_dashboard(request: Request):
    """Web admin dashboard."""
    return templates.TemplateResponse(
        request, "index.html", {"asset_v": _asset_version()}
    )


@app.get("/boshqaruv", include_in_schema=False)
async def platform_panel(request: Request):
    """Platform operator's panel. Same origin as the business panel by design —
    one deploy, one database, one migration chain — but a separate page behind a
    separate session cookie."""
    return templates.TemplateResponse(
        request, "platform.html", {"asset_v": _asset_version()}
    )


@app.get("/api/health")
async def health_check():
    """Liveness: is the process up? Deliberately does not touch the database —
    a container probe must not fail (and restart the app) over a slow query."""
    return {"status": "healthy", "service": "Sotuvchi AI", "version": app.version}


@app.get("/api/ready")
async def readiness_check():
    """Readiness: can we actually serve? A process that cannot reach Postgres
    answers no request usefully, so the load balancer should not send it any."""
    try:
        async with AsyncSessionLocal() as session:
            await session.execute(text("SELECT 1"))
        return {"status": "ready", "database": "ok"}
    except Exception as e:
        logger.error(f"Readiness check failed: {e}")
        return JSONResponse(
            status_code=503, content={"status": "not_ready", "database": "unreachable"}
        )


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError):
    """One readable sentence instead of FastAPI's array of error objects.

    Every panel reads `detail` as text; handed a list it printed
    "[object Object]", so a user who typed a short password was told nothing.
    """
    messages = []
    for err in exc.errors():
        msg = err.get("msg", "")
        # Pydantic prefixes messages raised by a validator; the Uzbek sentence
        # after it is the part written for the person reading it.
        messages.append(msg.split("Value error, ", 1)[-1])
    return JSONResponse(status_code=422, content={"detail": " ".join(messages) or "Ma'lumot noto'g'ri."})


if __name__ == "__main__":
    # Development only. In a container the CMD runs uvicorn itself, so workers,
    # proxy headers and graceful shutdown are the server's job, not ours.
    import uvicorn

    if settings.HOST == "0.0.0.0":
        # Print the LAN address so the panel can be opened from a phone on the
        # same Wi-Fi — 127.0.0.1 is reachable only from this machine.
        import socket

        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))  # no packets sent; just picks the route
            lan_ip = s.getsockname()[0]
            s.close()
            print(f"\n  Shu kompyuterda:  http://127.0.0.1:{settings.PORT}")
            print(f"  Telefondan (bir xil Wi-Fi):  http://{lan_ip}:{settings.PORT}\n")
        except Exception:
            pass

    uvicorn.run("main:app", host=settings.HOST, port=settings.PORT, reload=False)
