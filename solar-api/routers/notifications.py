from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from config import settings
import telegram

router = APIRouter()

class TelegramConfig(BaseModel):
    chat_id: str

@router.get("/detect-chat-id")
@router.get("/chat-id")
async def auto_detect_chat_id():
    """Auto-detect chat ID from first message sent to bot"""
    cid = await telegram.get_chat_id()
    if not cid:
        raise HTTPException(status_code=404, detail="No messages found. Please send /start to your bot first.")
    return {"chat_id": cid}

@router.post("/test")
async def send_test_message():
    """Send a test Telegram message"""
    ok = await telegram.send_message(
        "✅ <b>SolarWatch Pro</b>\n\nYour Telegram notifications are working!\n\n"
        "You'll receive:\n• Daily morning reports\n• Fault alerts\n• Weekly summaries\n\n"
        "<i>This is a test message.</i>"
    )
    if not ok:
        raise HTTPException(status_code=500, detail="Failed to send. Check TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID in .env")
    return {"status": "sent", "message": "Test message delivered to Telegram"}

@router.get("/status")
async def telegram_status():
    return {
        "configured": bool(settings.telegram_bot_token and settings.telegram_chat_id),
        "bot_token_set": bool(settings.telegram_bot_token),
        "chat_id_set": bool(settings.telegram_chat_id),
        "bot_url": f"https://t.me/Solarwatchpro_bot"
    }
