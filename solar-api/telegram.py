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


def format_daily_report(
    date_str: str,
    kwh: float,
    expected_kwh: float,
    pr_pct: float,
    saved_inr: float,
    bill_without_inr: float,
    co2_kg: float,
    health_score: int,
    weather_desc: str,
    sun_hours: float,
    recovered_inr: float,
    payback_pct: float,
    system_cost_inr: float,
    ai_analysis: str = "",
) -> str:
    location = settings.location_name or "Solar System"
    return (
        f"☀️ <b>Daily Solar Report — {date_str}</b>\n"
        f"📍 {location}\n\n"
        f"⚡ <b>Generation:</b> {kwh:.1f} kWh\n"
        f"   <i>(Expected: {expected_kwh:.1f} kWh | PR: {pr_pct:.0f}%)</i>\n"
        f"💰 <b>Saved:</b> ₹{saved_inr:.0f}\n"
        f"   <i>(Without solar: ₹{bill_without_inr:.0f})</i>\n"
        f"🌿 <b>CO₂ offset:</b> {co2_kg:.1f} kg\n"
        f"📊 <b>Health:</b> {health_score}/100\n"
        f"🌤 <b>Weather:</b> {weather_desc} | {sun_hours:.1f} sun hrs\n"
        + (f"\n🤖 <b>AI Analysis:</b>\n{ai_analysis}\n" if ai_analysis else "")
        + f"\n💼 <b>Investment recovered:</b> ₹{recovered_inr:,.0f}\n"
        f"   <i>{payback_pct:.1f}% of ₹{system_cost_inr:,.0f}</i>\n\n"
        f"<i>SolarWatch Pro • {date_str}</i>"
    )


def format_weekly_report(
    date_range: str,
    kwh: float,
    savings_inr: float,
    co2_kg: float,
    avg_health: float,
    best_day_kwh: float,
) -> str:
    location = settings.location_name or "Solar System"
    return (
        f"📅 <b>Weekly Solar Report</b>\n"
        f"📍 {location} | {date_range}\n\n"
        f"⚡ <b>Generated:</b> {kwh:.1f} kWh\n"
        f"💰 <b>Saved:</b> ₹{savings_inr:.0f}\n"
        f"🌿 <b>CO₂ offset:</b> {co2_kg:.1f} kg\n"
        f"📊 <b>Avg health:</b> {avg_health:.0f}/100\n"
        f"🏆 <b>Best day:</b> {best_day_kwh:.1f} kWh\n\n"
        f"<i>SolarWatch Pro — 7-day summary</i>"
    )


def format_monthly_report(
    month_str: str,
    kwh: float,
    savings_inr: float,
    bill_without_inr: float,
    co2_kg: float,
    payback_pct: float,
    system_cost_inr: float,
) -> str:
    location = settings.location_name or "Solar System"
    return (
        f"📆 <b>Monthly Solar Report — {month_str}</b>\n"
        f"📍 {location}\n\n"
        f"⚡ <b>Generated:</b> {kwh:.1f} kWh\n"
        f"💰 <b>Bill saved:</b> ₹{savings_inr:.0f}\n"
        f"   <i>Without solar: ₹{bill_without_inr:.0f}</i>\n"
        f"🌿 <b>CO₂ offset:</b> {co2_kg:.1f} kg\n"
        f"💼 <b>Payback progress:</b> {payback_pct:.1f}% of ₹{system_cost_inr:,.0f}\n\n"
        f"<i>SolarWatch Pro — monthly summary</i>"
    )


def format_alert(title: str, detail: str, severity: str = "warning") -> str:
    icon = "🚨" if severity == "critical" else "⚠️"
    return (
        f"{icon} <b>SOLAR ALERT</b>\n"
        f"<b>{title}</b>\n\n"
        f"{detail}\n\n"
        f"<i>Open your SolarWatch dashboard for details</i>"
    )


def format_fault_alert(fault_code: str, fault_info: dict) -> str:
    severity_icon = "🚨" if fault_info.get("severity") == "critical" else "⚠️"
    auto = "✅ Auto-resolves" if fault_info.get("auto_resolves") else "🔧 Requires action"
    return (
        f"{severity_icon} <b>Inverter Fault: {fault_code}</b>\n"
        f"<b>{fault_info.get('name', fault_code)}</b>\n\n"
        f"📋 <b>What happened:</b>\n{fault_info.get('plain_english', '')}\n\n"
        f"🛠 <b>Action:</b>\n{fault_info.get('action', 'Contact installer.')}\n\n"
        f"{auto}\n"
        f"<i>SolarWatch Pro — KSY 3.4KW fault decoder</i>"
    )
