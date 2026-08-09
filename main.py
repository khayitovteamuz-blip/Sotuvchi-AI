import sys
from pathlib import Path

# Ensure virtual environment site-packages is in sys.path
venv_site_packages = Path(__file__).parent / ".venv" / "lib" / "python3.9" / "site-packages"
if venv_site_packages.exists() and str(venv_site_packages) not in sys.path:
    sys.path.insert(0, str(venv_site_packages))

import logging
from contextlib import asynccontextmanager

import uvicorn
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.chat_api import router as chat_router
from app.api.admin_api import router as admin_router
from app.api.bot_webhook import router as bot_router
from app.api.auth_api import router as auth_router
from app.api.inbox_api import router as inbox_router
from app.api.integrations_api import router as integrations_router
from app.services.telegram_poller import telegram_poller

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Long-polling lets the Telegram bot work on localhost (no public URL).
    if settings.TELEGRAM_POLLING:
        await telegram_poller.start()
    yield
    if settings.TELEGRAM_POLLING:
        await telegram_poller.stop()


app = FastAPI(
    title="Sotuvchi AI - Enterprise Sales Agent",
    description="O'zbek tilidagi avtonom AI Sotuvchi agenti, Telegram bot integratsiyasi va Google Sheets CRM boshqaruv paneli.",
    version="2.0.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static files & templates
static_dir = Path(__file__).parent / "static"
static_dir.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

templates_dir = Path(__file__).parent / "templates"
templates_dir.mkdir(exist_ok=True)
templates = Jinja2Templates(directory=str(templates_dir))

# Include API Routers
app.include_router(auth_router)
app.include_router(chat_router)
app.include_router(admin_router)
app.include_router(bot_router)
app.include_router(inbox_router)
app.include_router(integrations_router)


def _asset_version() -> str:
    """Cache-buster derived from the assets themselves.

    A hand-written ?v=3.0 goes stale the moment the file changes again, and the
    browser then serves old JS against new HTML — which looks like broken
    features, not a caching bug. Deriving it from mtimes makes that impossible.
    """
    stamp = 0.0
    for rel in ("js/app.js", "css/style.css"):
        f = static_dir / rel
        if f.exists():
            stamp = max(stamp, f.stat().st_mtime)
    return str(int(stamp))


@app.get("/")
async def root_dashboard(request: Request):
    """Serve Web Admin Dashboard & Live AI Simulator"""
    return templates.TemplateResponse(
        "index.html", {"request": request, "asset_v": _asset_version()}
    )


@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "service": "Sotuvchi AI",
        "version": "1.0.0"
    }


if __name__ == "__main__":
    import os
    os.system("lsof -ti:8080 | xargs kill -9 2>/dev/null || true")
    host, port = settings.HOST, settings.PORT

    # Print the LAN address so the panel can be opened from a phone on the same
    # Wi-Fi — 127.0.0.1 is reachable only from this machine.
    if host == "0.0.0.0":
        import socket
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))          # no packets sent; just picks the route
            lan_ip = s.getsockname()[0]
            s.close()
            print(f"\n  Shu kompyuterda:  http://127.0.0.1:{port}")
            print(f"  Telefondan (bir xil Wi-Fi):  http://{lan_ip}:{port}\n")
        except Exception:
            pass

    uvicorn.run(
        app,
        host=host,
        port=port,
        reload=False,
        loop="asyncio",
        http="h11",
        ws="none",
    )
