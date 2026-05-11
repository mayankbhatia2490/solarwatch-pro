import httpx
import logging
from config import settings

logger = logging.getLogger(__name__)

TELEGRAM_API = f"https://api.telegram.org/bot{settings.telegram_bot_token}"

async def send_message(text: str, chat_id: str = None, parse_mode: str = "HTML") -> bool:
    cid = chat_id or settings.telegram_chat_id
    if not settings.telegram_bot_token or not cid:
        logger.warning("Telegram not configured — skipping message")
        return False
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{TELEGRAM_API}/sendMessage",
                json={"chat_id": cid, "text": text, "parse_mode": parse_mode},
                timeout=10
            )
            r.raise_for_status()
            return True
    except Exception as e:
        logger.error(f"Telegram send failed: {e}")
        return False

async def get_chat_id() -> str | None:
    """Auto-detect chat ID from first /start message"""
    if not settings.telegram_bot_token:
        return None
    try:
        async with httpx.AsyncClient() as client:
            r = await client.get(f"{TELEGRAM_API}/getUpdates", timeout=10)
            data = r.json()
            updates = data.get("result", [])
            if updates:
                return str(updates[-1]["message"]["chat"]["id"])
    except Exception as e:
        logger.error(f"getUpdates failed: {e}")
    return None

def format_daily_report(power_w: float, energy_kwh: float, savings_inr: float,
                         health_score: int, co2_kg: float, tariff: float) -> str:
    status = "🟢 Generating" if power_w > 0 else "⚫ Offline / Night"
    return (
        f"🌞 <b>SolarWatch Daily Report</b>\n\n"
        f"⚡ <b>Right Now:</b> {power_w:.0f} W — {status}\n"
        f"📦 <b>Today's Generation:</b> {energy_kwh:.1f} kWh\n"
        f"💰 <b>Today's Savings:</b> ₹{savings_inr:.0f}\n"
        f"🌿 <b>CO₂ Offset:</b> {co2_kg:.1f} kg\n"
        f"🏥 <b>System Health:</b> {health_score}/100\n\n"
        f"<i>SolarWatch Pro • Your system is being monitored 24/7</i>"
    )

def format_alert(title: str, detail: str, severity: str = "warning") -> str:
    icon = "🚨" if severity == "critical" else "⚠️"
    return (
        f"{icon} <b>SOLAR ALERT</b>\n"
        f"<b>{title}</b>\n\n"
        f"{detail}\n\n"
        f"<i>Open your SolarWatch dashboard for details</i>"
    )
