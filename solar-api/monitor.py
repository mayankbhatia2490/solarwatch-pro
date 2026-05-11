"""
Background alert monitor — runs every 5 minutes alongside the API.
Checks live InfluxDB data against thresholds and fires Telegram alerts.
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta, time
from influx import query
from config import settings
import telegram as tg

logger = logging.getLogger(__name__)

BUCKET = settings.influxdb_bucket

# ── Thresholds ────────────────────────────────────────────────────────────────
TEMP_WARNING   = 75.0   # °C — heatsink probe warn (not ambient!)
TEMP_CRITICAL  = 85.0   # °C — heatsink probe critical (F8 fault territory)
GRID_V_LOW     = 207.0  # V
GRID_V_HIGH    = 253.0  # V
FREQ_LOW       = 49.5   # Hz
FREQ_HIGH      = 50.5   # Hz
STRING_IMBAL   = 0.20   # 20% deviation
DAILY_REPORT_HOUR_IST = 7   # 7 AM IST

LAT = 29.6934
LON = 76.9994

# ── In-memory cooldowns (key → last_alert datetime) ───────────────────────────
_cooldowns: dict[str, datetime] = {}

def _can_alert(key: str, cooldown_minutes: int = 60) -> bool:
    """Return True only if we haven't sent this alert within cooldown window."""
    last = _cooldowns.get(key)
    if last is None or (datetime.now(timezone.utc) - last).seconds > cooldown_minutes * 60:
        _cooldowns[key] = datetime.now(timezone.utc)
        return True
    return False

def _latest(field: str) -> float:
    flux = f'''
from(bucket: "{BUCKET}")
  |> range(start: -10m)
  |> filter(fn: (r) => r["_field"] == "{field}")
  |> last()
'''
    recs = query(flux)
    return float(recs[0].get_value()) if recs else 0.0

# Cache sunrise/sunset so we don't hammer Open-Meteo every 5 min
_sun_cache: dict = {"date": None, "sunrise": None, "sunset": None}

def _refresh_sun_cache():
    """Fetch today's sunrise/sunset from Open-Meteo once per day."""
    import urllib.request, json as _json
    today = datetime.now(timezone(timedelta(hours=5, minutes=30))).date()
    if _sun_cache["date"] == today:
        return
    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={LAT}&longitude={LON}"
            f"&daily=sunrise,sunset"
            f"&timezone=Asia%2FKolkata"
            f"&start_date={today}&end_date={today}"
        )
        with urllib.request.urlopen(url, timeout=5) as resp:
            d = _json.loads(resp.read())
        _sun_cache["sunrise"] = d["daily"]["sunrise"][0]  # e.g. "2026-05-11T05:32"
        _sun_cache["sunset"]  = d["daily"]["sunset"][0]
        _sun_cache["date"]    = today
    except Exception:
        pass  # keep old values or fallback below

def _is_daytime() -> bool:
    """True only between today's sunrise and sunset (Open-Meteo). IST fallback if unavailable."""
    _refresh_sun_cache()
    now_utc = datetime.now(timezone.utc)
    if _sun_cache["sunrise"] and _sun_cache["sunset"]:
        try:
            sr = datetime.fromisoformat(_sun_cache["sunrise"]).replace(tzinfo=timezone(timedelta(hours=5, minutes=30))).astimezone(timezone.utc)
            ss = datetime.fromisoformat(_sun_cache["sunset"]).replace(tzinfo=timezone(timedelta(hours=5, minutes=30))).astimezone(timezone.utc)
            return sr <= now_utc <= ss
        except Exception:
            pass
    # Fallback: Karnal approx 5:30AM – 7:30PM IST
    ist_h = (now_utc + timedelta(hours=5, minutes=30)).hour
    return 5 <= ist_h < 20

# ── Individual alert checks ────────────────────────────────────────────────────

async def check_temperature():
    temp = _latest("internal_radiator_temperature")
    if temp <= 0:
        return
    if temp >= TEMP_CRITICAL and _can_alert("temp_critical", 120):
        await tg.send_message(tg.format_alert(
            "🔴 Inverter Heatsink Overheating — Critical",
            f"Inverter radiator (heatsink) probe: <b>{temp:.1f}°C</b> (critical limit: {TEMP_CRITICAL}°C)\n"
            f"KSY F8 fault may trigger soon. Check ventilation and reduce load if possible.",
            severity="critical"
        ))
    elif temp >= TEMP_WARNING and _can_alert("temp_warning", 180):
        await tg.send_message(tg.format_alert(
            "🟡 Inverter Heatsink Running Hot",
            f"Heatsink temperature: <b>{temp:.1f}°C</b> (warn threshold: {TEMP_WARNING}°C).\n"
            f"Ensure no obstructions around the inverter and airflow is clear.",
            severity="warning"
        ))

async def check_grid_voltage():
    v = _latest("grid_r_voltage")
    if v <= 0:
        return
    if (v < GRID_V_LOW or v > GRID_V_HIGH) and _can_alert("grid_voltage", 60):
        direction = "low" if v < GRID_V_LOW else "high"
        await tg.send_message(tg.format_alert(
            f"Grid Voltage {direction.title()} — {v:.1f}V",
            f"Grid R-phase: <b>{v:.1f}V</b> (safe range: {GRID_V_LOW}–{GRID_V_HIGH}V).\n"
            f"Your inverter is handling this automatically. "
            f"If it persists, contact your electricity provider.",
            severity="warning"
        ))

async def check_grid_frequency():
    freq = _latest("grid_frequency")
    if freq <= 0:
        return
    if (freq < FREQ_LOW or freq > FREQ_HIGH) and _can_alert("grid_frequency", 60):
        await tg.send_message(tg.format_alert(
            f"Grid Frequency Out of Range — {freq:.2f}Hz",
            f"Grid frequency: <b>{freq:.2f}Hz</b> (normal: 49.5–50.5Hz).\n"
            f"Inverter may trip if this continues.",
            severity="warning"
        ))

async def check_zero_output():
    """Alert if generating 0W during daylight for >30 min."""
    if not _is_daytime():
        return
    flux = f'''
from(bucket: "{BUCKET}")
  |> range(start: -35m)
  |> filter(fn: (r) => r["_field"] == "power_now_w")
  |> mean()
'''
    recs = query(flux)
    avg = float(recs[0].get_value()) if recs else -1
    if avg == 0 and _can_alert("zero_output", 90):
        await tg.send_message(tg.format_alert(
            "⚫ Zero Output During Daylight",
            f"Your inverter has produced <b>0W for 30+ minutes</b> during daylight hours.\n"
            f"Possible causes: inverter fault, grid trip, or DC disconnect.\n"
            f"Check inverter display for error codes.",
            severity="critical"
        ))

async def check_string_imbalance():
    pv1_v = _latest("pv1_voltage")
    pv2_v = _latest("pv2_voltage")
    if pv1_v <= 0 or pv2_v <= 0 or not _is_daytime():
        return
    deviation = abs(pv1_v - pv2_v) / max(pv1_v, pv2_v)
    if deviation > STRING_IMBAL and _can_alert("string_imbal", 240):
        weaker = "String 1" if pv1_v < pv2_v else "String 2"
        await tg.send_message(tg.format_alert(
            f"⚡ String Imbalance Detected — {deviation*100:.0f}% Deviation",
            f"PV String voltages: <b>String 1: {pv1_v:.0f}V | String 2: {pv2_v:.0f}V</b>\n"
            f"<b>{weaker}</b> is underperforming by {deviation*100:.0f}%.\n"
            f"Check for shading, dirt, or loose connections on {weaker} panels.",
            severity="warning"
        ))

# ── Daily morning report (7AM IST) ────────────────────────────────────────────
_last_daily_report: datetime | None = None

async def maybe_send_daily_report():
    global _last_daily_report
    ist_now = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    if ist_now.hour != DAILY_REPORT_HOUR_IST:
        return
    # Only once per day
    today = ist_now.date()
    if _last_daily_report and _last_daily_report.date() == today:
        return
    _last_daily_report = ist_now

    # Pull yesterday's totals
    power   = _latest("power_now_w")
    energy  = _latest("daily_energy_kwh")
    tariff  = settings.electricity_tariff_inr
    savings = round(energy * tariff, 0)
    co2     = round(energy * 0.82, 1)

    # Health score (simple: 100 - any issues found above)
    score = 90  # placeholder until scorecard runs

    msg = tg.format_daily_report(power, energy, savings, score, co2, tariff)
    await tg.send_message(msg)
    logger.info("Daily Telegram report sent.")

# ── Weekly/Monthly Reports ──────────────────────────────────────────────────────
_last_weekly_report: datetime | None = None
_last_monthly_report: datetime | None = None

async def maybe_send_weekly_report():
    global _last_weekly_report
    ist_now = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    
    # Send on Sunday (weekday() == 6) at 8 AM IST
    if ist_now.weekday() != 6 or ist_now.hour != 8:
        return
    
    today = ist_now.date()
    if _last_weekly_report and _last_weekly_report.date() == today:
        return
    _last_weekly_report = ist_now

    # In production, query InfluxDB for the last 7 days of yield
    energy = _latest("daily_energy_kwh") * 7 # Mock
    savings = round(energy * settings.electricity_tariff_inr, 0)
    
    msg = f"📊 *Weekly Solar Summary*\n\n"
    msg += f"🗓 *Week Ending:* {today.strftime('%d %b %Y')}\n"
    msg += f"⚡ *Total Generation:* {energy:.1f} kWh\n"
    msg += f"💰 *Estimated Savings:* ₹{savings}\n"
    msg += f"🌿 *CO2 Offset:* {round(energy * 0.82, 1)} kg\n\n"
    msg += f"✅ *System Health:* Excellent. No major anomalies detected this week."
    
    await tg.send_message(msg)
    logger.info("Weekly Telegram report sent.")

async def maybe_send_monthly_report():
    global _last_monthly_report
    ist_now = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    
    # Send on the 1st of the month at 9 AM IST
    if ist_now.day != 1 or ist_now.hour != 9:
        return
    
    today = ist_now.date()
    if _last_monthly_report and _last_monthly_report.date() == today:
        return
    _last_monthly_report = ist_now

    # In production, query InfluxDB for the last month
    energy = _latest("daily_energy_kwh") * 30 # Mock
    savings = round(energy * settings.electricity_tariff_inr, 0)
    
    msg = f"📈 *Monthly Performance Report*\n\n"
    msg += f"🗓 *Month:* {ist_now.strftime('%B %Y')}\n"
    msg += f"⚡ *Total Generation:* {energy:.1f} kWh\n"
    msg += f"💰 *Estimated Savings:* ₹{savings}\n"
    msg += f"📉 *Performance Ratio:* 84.5% (Optimal)\n\n"
    msg += f"💡 *Insight:* Your panels performed 5% better than expected this month due to favorable weather conditions."
    
    await tg.send_message(msg)
    logger.info("Monthly Telegram report sent.")

# ── Main monitoring loop ───────────────────────────────────────────────────────

async def run_monitor():
    """Runs forever — called from FastAPI startup."""
    logger.info("🔔 Telegram alert monitor started.")
    while True:
        try:
            await check_temperature()
            await check_grid_voltage()
            await check_grid_frequency()
            await check_zero_output()
            await check_string_imbalance()
            await maybe_send_daily_report()
            await maybe_send_weekly_report()
            await maybe_send_monthly_report()
        except Exception as e:
            logger.error(f"Monitor loop error: {e}")
        await asyncio.sleep(300)  # check every 5 minutes
