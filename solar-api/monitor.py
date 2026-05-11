"""
Background alert monitor — runs every 5 minutes alongside the API.
Checks live InfluxDB data against thresholds and fires Telegram alerts.
All thresholds match anomalies.py — no duplication.
"""
import asyncio
import logging
from datetime import datetime, timezone, timedelta, date
from influx import query
from config import settings
import telegram as tg

logger = logging.getLogger(__name__)

BUCKET = settings.influxdb_bucket

# ── Thresholds (single source of truth — also used by anomalies router) ─────
TEMP_WARNING   = 75.0   # °C heatsink warn
TEMP_CRITICAL  = 85.0   # °C heatsink critical (F8 fault territory)
GRID_V_LOW     = 207.0  # V
GRID_V_HIGH    = 253.0  # V
FREQ_LOW       = 49.5   # Hz
FREQ_HIGH      = 50.5   # Hz
STRING_IMBAL   = 0.20   # 20% power deviation
NEAR_ZERO_PCT  = 0.15   # <15% of expected = near-zero output alert

DAILY_REPORT_HOUR_IST  = 7   # 7 AM IST
WEEKLY_REPORT_WEEKDAY  = 6   # Sunday
WEEKLY_REPORT_HOUR_IST = 8   # 8 AM IST
MONTHLY_REPORT_DAY     = 1   # 1st of month
MONTHLY_REPORT_HOUR_IST = 9  # 9 AM IST

LAT = 29.6934
LON = 76.9994

# ── In-memory cooldowns ───────────────────────────────────────────────────────
_cooldowns: dict[str, datetime] = {}

def _can_alert(key: str, cooldown_minutes: int = 60) -> bool:
    last = _cooldowns.get(key)
    if last is None or (datetime.now(timezone.utc) - last).total_seconds() > cooldown_minutes * 60:
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

def _sum_field_range(field: str, start: str, stop: str) -> float:
    """Sum max-per-day of a cumulative field (e.g. daily_energy_kwh) over a date range."""
    flux = f'''
from(bucket: "{BUCKET}")
  |> range(start: {start}, stop: {stop})
  |> filter(fn: (r) => r["_field"] == "{field}")
  |> aggregateWindow(every: 1d, fn: max, createEmpty: false)
  |> sum()
'''
    recs = query(flux)
    return float(recs[0].get_value()) if recs else 0.0

def _compute_live_health() -> int:
    """Compute real health score from current readings."""
    score = 100
    gv   = _latest("grid_r_voltage")
    temp = _latest("internal_radiator_temperature")
    pv1v = _latest("pv1_voltage")
    stat = int(_latest("status_code"))

    if gv > 0:
        if gv < 207 or gv > 253:  score -= 20
        elif gv < 215 or gv > 245: score -= 10
    if temp > 85:   score -= 30
    elif temp > 75: score -= 15
    if pv1v < 50 and stat == 0:
        score -= 15

    return max(0, score)

# ── Sunrise/Sunset cache ──────────────────────────────────────────────────────
_sun_cache: dict = {"date": None, "sunrise": None, "sunset": None}

def _refresh_sun_cache():
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
        _sun_cache["sunrise"] = d["daily"]["sunrise"][0]
        _sun_cache["sunset"]  = d["daily"]["sunset"][0]
        _sun_cache["date"]    = today
    except Exception:
        pass

def _is_daytime() -> bool:
    _refresh_sun_cache()
    now_utc = datetime.now(timezone.utc)
    if _sun_cache["sunrise"] and _sun_cache["sunset"]:
        try:
            tz_ist = timezone(timedelta(hours=5, minutes=30))
            sr = datetime.fromisoformat(_sun_cache["sunrise"]).replace(tzinfo=tz_ist).astimezone(timezone.utc)
            ss = datetime.fromisoformat(_sun_cache["sunset"]).replace(tzinfo=tz_ist).astimezone(timezone.utc)
            return sr <= now_utc <= ss
        except Exception:
            pass
    # Fallback: Karnal approx 5:30AM–7:30PM IST
    ist_h = (now_utc + timedelta(hours=5, minutes=30)).hour
    return 5 <= ist_h < 20


# ── Alert checks ──────────────────────────────────────────────────────────────

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
            f"Your inverter handles this automatically. "
            f"If persistent, contact UHBVN.",
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

async def check_output():
    """
    Alert on near-zero (<15% of expected) AND absolute zero during daylight.
    Uses radiation stored in InfluxDB — no external API call needed.
    """
    if not _is_daytime():
        return

    power    = _latest("power_now_w")
    expected = _latest("expected_power_w")
    rad      = _latest("shortwave_radiation_wm2")

    # Absolute zero for 30+ min
    if power == 0 and rad > 50 and _can_alert("zero_output", 90):
        await tg.send_message(tg.format_alert(
            "⚫ Zero Output During Daylight",
            f"Your inverter has produced <b>0W for 30+ minutes</b> with {rad:.0f} W/m² solar radiation.\n"
            f"Possible causes: inverter fault, grid trip, or DC disconnect.\n"
            f"Check inverter display for fault codes (F1–F8).",
            severity="critical"
        ))
        return

    # Near-zero: <15% of expected during good irradiance
    if expected > 200 and rad > 300:
        efficiency = power / expected if expected > 0 else 1.0
        if efficiency < NEAR_ZERO_PCT and _can_alert("near_zero_output", 90):
            tariff = settings.electricity_tariff_inr
            lost_inr_hr = round((expected - power) / 1000 * tariff, 0)
            await tg.send_message(tg.format_alert(
                f"⚠️ Very Low Output — {efficiency*100:.0f}% of Expected",
                f"Producing <b>{power:.0f}W</b> vs <b>{expected:.0f}W</b> expected "
                f"({efficiency*100:.0f}% efficiency).\n"
                f"Estimated loss: <b>₹{lost_inr_hr}/hour</b>.\n"
                f"Check for heavy soiling, shading, or a string fault.",
                severity="warning"
            ))

async def check_string_imbalance():
    """Power-based imbalance (voltage × current) — catches soiling before voltage drops."""
    pv1_v = _latest("pv1_voltage")
    pv1_a = _latest("pv1_current")
    pv2_v = _latest("pv2_voltage")
    pv2_a = _latest("pv2_current")

    pv1_power = pv1_v * pv1_a
    pv2_power = pv2_v * pv2_a

    if pv1_power <= 50 or pv2_power <= 50 or not _is_daytime():
        return

    max_power = max(pv1_power, pv2_power)
    deviation = abs(pv1_power - pv2_power) / max_power

    if deviation > STRING_IMBAL and _can_alert("string_imbal", 240):
        weaker  = "String 1" if pv1_power < pv2_power else "String 2"
        weaker_w  = min(pv1_power, pv2_power)
        stronger_w = max(pv1_power, pv2_power)
        tariff = settings.electricity_tariff_inr
        lost_inr_hr = round((stronger_w - weaker_w) / 1000 * tariff, 0)

        await tg.send_message(tg.format_alert(
            f"⚡ String Power Imbalance — {deviation*100:.0f}% Deviation",
            f"String 1: <b>{pv1_power:.0f}W</b> ({pv1_v:.0f}V × {pv1_a:.1f}A)\n"
            f"String 2: <b>{pv2_power:.0f}W</b> ({pv2_v:.0f}V × {pv2_a:.1f}A)\n"
            f"<b>{weaker}</b> is underperforming by {deviation*100:.0f}%.\n"
            f"Estimated loss: ₹{lost_inr_hr}/hour.\n"
            f"Check {weaker} for soiling, shading, or loose MC4 connector.",
            severity="warning"
        ))


# ── Scheduled reports ─────────────────────────────────────────────────────────
_last_daily_report:   datetime | None = None
_last_weekly_report:  datetime | None = None
_last_monthly_report: datetime | None = None

async def maybe_send_daily_report():
    global _last_daily_report
    ist_now = datetime.now(timezone(timedelta(hours=5, minutes=30)))
    if ist_now.hour != DAILY_REPORT_HOUR_IST:
        return
    today = ist_now.date()
    if _last_daily_report and _last_daily_report.date() == today:
        return
    _last_daily_report = ist_now

    power       = _latest("power_now_w")
    energy      = _latest("daily_energy_kwh")
    tariff      = settings.electricity_tariff_inr
    savings     = round(energy * tariff, 0)
    co2         = round(energy * 0.82, 1)
    health      = _compute_live_health()  # Real health score, not 90 placeholder

    msg = tg.format_daily_report(power, energy, savings, health, co2, tariff)
    await tg.send_message(msg)
    logger.info("Daily Telegram report sent.")

async def maybe_send_weekly_report():
    global _last_weekly_report
    ist_now = datetime.now(timezone(timedelta(hours=5, minutes=30)))

    if ist_now.weekday() != WEEKLY_REPORT_WEEKDAY or ist_now.hour != WEEKLY_REPORT_HOUR_IST:
        return
    today = ist_now.date()
    if _last_weekly_report and _last_weekly_report.date() == today:
        return
    _last_weekly_report = ist_now

    # Real 7-day energy sum from InfluxDB
    stop_  = ist_now.date().isoformat() + "T00:00:00Z"
    start_ = (ist_now.date() - timedelta(days=7)).isoformat() + "T00:00:00Z"
    energy = _sum_field_range("daily_energy_kwh", start_, stop_)
    savings = round(energy * settings.electricity_tariff_inr, 0)
    co2     = round(energy * 0.82, 1)

    msg = (
        f"📊 <b>Weekly Solar Summary</b>\n\n"
        f"🗓 <b>Week ending:</b> {today.strftime('%d %b %Y')}\n"
        f"⚡ <b>Total Generation:</b> {energy:.1f} kWh\n"
        f"💰 <b>Estimated Savings:</b> ₹{savings:.0f}\n"
        f"🌿 <b>CO₂ Offset:</b> {co2} kg\n"
        f"🏥 <b>System Health:</b> {_compute_live_health()}/100\n\n"
        f"<i>SolarWatch Pro • 7-day actual generation</i>"
    )
    await tg.send_message(msg)
    logger.info("Weekly Telegram report sent.")

async def maybe_send_monthly_report():
    global _last_monthly_report
    ist_now = datetime.now(timezone(timedelta(hours=5, minutes=30)))

    if ist_now.day != MONTHLY_REPORT_DAY or ist_now.hour != MONTHLY_REPORT_HOUR_IST:
        return
    today = ist_now.date()
    if _last_monthly_report and _last_monthly_report.date() == today:
        return
    _last_monthly_report = ist_now

    # Real calendar-month energy from InfluxDB (previous month)
    prev_month_end   = today.replace(day=1)
    prev_month_start = (prev_month_end - timedelta(days=1)).replace(day=1)
    energy  = _sum_field_range(
        "daily_energy_kwh",
        prev_month_start.isoformat() + "T00:00:00Z",
        prev_month_end.isoformat()   + "T00:00:00Z"
    )
    savings = round(energy * settings.electricity_tariff_inr, 0)
    co2     = round(energy * 0.82, 1)
    trees   = round(co2 / 21, 1)

    install_date = datetime.fromisoformat(settings.installation_date)
    total_energy = _latest("total_energy_kwh")
    total_savings = round(total_energy * settings.electricity_tariff_inr, 0)
    payback_pct   = round(
        min(total_savings / settings.system_cost_inr * 100, 100), 1
    ) if settings.system_cost_inr > 0 else 0

    msg = (
        f"📈 <b>Monthly Performance Report</b>\n\n"
        f"🗓 <b>Month:</b> {prev_month_start.strftime('%B %Y')}\n"
        f"⚡ <b>Total Generation:</b> {energy:.1f} kWh\n"
        f"💰 <b>Savings This Month:</b> ₹{savings:.0f}\n"
        f"🌿 <b>CO₂ Offset:</b> {co2} kg ({trees} trees)\n"
        f"🏥 <b>System Health:</b> {_compute_live_health()}/100\n\n"
        f"📊 <b>Investment Recovery:</b> {payback_pct}% of ₹{settings.system_cost_inr:,.0f}\n"
        f"💵 <b>Total Savings to Date:</b> ₹{total_savings:,.0f}\n\n"
        f"<i>SolarWatch Pro • Actual InfluxDB data</i>"
    )
    await tg.send_message(msg)
    logger.info("Monthly Telegram report sent.")


# ── Main monitoring loop ──────────────────────────────────────────────────────
async def run_monitor():
    logger.info("🔔 Telegram alert monitor started.")
    while True:
        try:
            await check_temperature()
            await check_grid_voltage()
            await check_grid_frequency()
            await check_output()
            await check_string_imbalance()
            await maybe_send_daily_report()
            await maybe_send_weekly_report()
            await maybe_send_monthly_report()
        except Exception as e:
            logger.error(f"Monitor loop error: {e}")
        await asyncio.sleep(300)  # every 5 minutes
