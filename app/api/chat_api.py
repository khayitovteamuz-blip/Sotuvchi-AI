from fastapi import APIRouter, HTTPException
from app.models.schema import ChatRequest, ChatResponse
from app.services.ai_agent import ai_agent

router = APIRouter(prefix="/api/chat", tags=["Chat"])


@router.post("", response_model=ChatResponse)
async def send_chat_message(request: ChatRequest):
    """Web Chat Simulator & Embedded Widget API endpoint"""
    if not request.message or not request.message.strip():
        raise HTTPException(status_code=400, detail="Xabar bo'sh bo'lishi mumkin emas.")

    response = ai_agent.generate_response(
        session_id=request.session_id,
        user_message=request.message,
        user_name=request.user_name or "Mijoz",
        telegram_id=request.telegram_id
    )
    return response
