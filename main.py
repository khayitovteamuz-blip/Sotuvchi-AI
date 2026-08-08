import sys
from pathlib import Path

# Ensure virtual environment site-packages is in sys.path
venv_site_packages = Path(__file__).parent / ".venv" / "lib" / "python3.9" / "site-packages"
if venv_site_packages.exists() and str(venv_site_packages) not in sys.path:
    sys.path.insert(0, str(venv_site_packages))

import uvicorn
from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.api.chat_api import router as chat_router
from app.api.admin_api import router as admin_router
from app.api.bot_webhook import router as bot_router

app = FastAPI(
    title="Sotuvchi AI - Enterprise Sales Agent",
    description="O'zbek tilidagi avtonom AI Sotuvchi agenti, Telegram bot integratsiyasi va Google Sheets CRM boshqaruv paneli.",
    version="1.0.0"
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
app.include_router(chat_router)
app.include_router(admin_router)
app.include_router(bot_router)


@app.get("/")
async def root_dashboard(request: Request):
    """Serve Web Admin Dashboard & Live AI Simulator"""
    return templates.TemplateResponse("index.html", {"request": request})


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
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8080,
        reload=False,
        loop="asyncio",
        http="h11",
        ws="none"
    )
