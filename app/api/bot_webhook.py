from fastapi import APIRouter, Request, HTTPException
from app.services.bot_service import bot_service

router = APIRouter(prefix="/api/bot", tags=["Telegram Bot Webhook"])


@router.post("/webhook")
async def telegram_webhook(request: Request):
    """Receive real-time updates from Telegram Webhook"""
    try:
        update = await request.json()
        await bot_service.handle_update(update)
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@router.get("/status")
async def bot_status():
    return {
        "bot_configured": bot_service.is_configured(),
        "token_set": bool(bot_service.token)
    }
