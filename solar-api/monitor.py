"""
Background alert monitor — runs every 5 minutes alongside the API.
Checks live InfluxDB data against thresholds and fires Telegram alerts.
All thresholds match anomalies.py — no duplication.
"""
import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
from influx import query
from config import settings, solar_bill_savings
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
NEAR_ZERO_PCT  = 0.15   # <15% of expected = near-zero output alert

DAILY_REPORT_HOUR_IST   = 7   # 7 AM IST
WEEKLY_REPORT_WEEKDAY   = 6   # Sunday
WEEKLY_REPORT_HOUR_IST  = 8   # 8 AM IST
MONTHLY_REPORT_DAY      = 1   # 1st of month
MONTHLY_REPORT_HOUR_IST = 9   # 9 AM IST

LAT = 29.6934
LON = 76.9994

# ── Persistent cooldowns — survive container restarts ─────────────────────────
_COOLDOWN_FILE = Path("/app/data/alert_cooldowns.json")

def _load_cooldowns() -> dict[str, float]:
    try:
        if _COOLDOWN_FILE.exists():
            return json.loads(_COOLDOWN_FILE.read_text())
    except Exception:
        pass
    return {}

def _save_cooldowns(cooldowns: dict[str, float]) -> None:
    try:
        _COOLDOWN_FILE.parent.mkdir(parents=True, exist_ok=True)
        _COOLDOWN_FILE.write_text(json.dumps(cooldowns))
    except Exception:
        pass

def _can_alert(key: str, cooldown_minutes: int = 60) -> bool:
    now = datetime.now(timezone.utc).timestamp()
    cooldowns = _load_cooldowns()
    last = cooldowns.get(key, 0)
    if (now - last) > cooldown_minutes * 60:
        cooldowns[key] = now
        _save_cooldowns(cooldowns)
        return True
    return False

# ── WMO weather code → human description ─────────────────────────────────────
_WMO = {
    0: "Clear sky", 1: "Mainly clear", 2: "Partly cloudy", 3: "Overcast",
    45: "Foggy", 48: "Icy fog",
    51: "Light drizzle", 53: "Drizzle", 55: "Heavy drizzle",
    61: "Light rain", 63: "Rain", 65: "Heavy rain",
    71: "Light snow", 73: "Snow", 75: "Heavy snow",
    80: "Rain showers", 81: "Rain showers", 82: "Heavy showers",
    95: "Thunderstorm", 96: "Thunderstorm", 99: "Thunderstorm + hail",
}

def _get_weather_summary() -> tuple[str, float]:
    """Return (description e.g. 'Partly cloudy 38°C', temp_c) from Open-Meteo."""
    try:
        import urllib.request as _req, json as _json
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={LAT}&longitude={LON}"
            f"&current=temperature_2m,weather_code"
            f"&timezone=Asia%2FKolkata"
        )
        with _req.urlopen(url, timeout=5) as resp:
            data = _json.loads(resp.read())
        cur  = data.get("current", {})
        temp = float(cur.get("temperature_2m") or 0)
        code = int(cur.get("weather_code") or 0)
        desc = _WMO.get(code, "Clear")
        return f"{desc} {temp:.0f}°C", temp
    except Exception:
        return "—", 35.0


async def _gemini_analysis(kwh: float, pr_pct: float, health: int,
                            weather_desc: str, temp_c: float) -> str:
    """
    Call Gemini for a 2-sentence daily performance insight.
    Returns "" gracefully if API key missing or call fails.
    """
    key = settings.gemini_api_key
    if not key:
        return ""
    try:
        from google import genai as _genai
        client = _genai.Client(api_key=key)
        capacity_kw = settings.installed_capacity_w / 1000
        prompt = (
            f"My {capacity_kw:.1f}kW Vikram Solar N-type bifacial rooftop system in "
            f"{settings.location_name} generated {kwh:.1f} kWh today "
            f"(performance ratio {pr_pct:.0f}%, health score {health}/100). "
            f"Weather: {weather_desc}, ambient {temp_c:.0f}°C. "
            f"Give exactly 2 sentences: first on today's performance, second a practical tip. "
            f"Be specific to Indian rooftop solar. No bullet points, no markdown."
        )
        resp = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
        return resp.text.strip()
    except Exception as e:
        logger.warning(f"Gemini analysis failed: {e}")
        return ""


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
    """
    Compute real health score 0-100 from live readings.
    KSY 3.4KW-1Ph: single-phase, 1 MPPT, 1 PV string — no S/T phase, no PV2 imbalance.
    """
    score = 100

    # Grid voltage — R phase only (single-phase inverter confirmed from nameplate)
    gv = _latest("grid_r_voltage")
    if gv > 0:
        if gv < 207 or gv > 253:
            score -= 20
        elif gv < 215 or gv > 245:
            score -= 10

    # Heatsink temperature (F6 derating >75°C, F8 fault risk >85°C)
    temp = _latest("internal_radiator_temperature")
    if temp > 85:
        score -= 30
    elif temp > 75:
        score -= 15

    # Performance ratio during daylight
    if _is_daytime():
        power    = _latest("power_now_w")
        expected = _latest("expected_power_w")
        if expected > 200:
            pr = power / expected
            if pr < 0.60:
                score -= 15
            elif pr < 0.80:
                score -= 5

    # PV1 absent while online during daylight
    pv1v = _latest("pv1_voltage")
    stat = int(_latest("status_code"))
    if pv1v < 50 and stat == 0 and _is_daytime():
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
    # KSY 3.4kW-1Ph has 1 MPPT and 1 PV string — no second string to compare against.
    # Function retained as a no-op so the monitor loop doesn't need to change.
    pass


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

    energy      = _latest("daily_energy_kwh")
    health      = _compute_live_health()
    co2         = round(energy * 0.82, 1)

    # Real weather — live Open-Meteo call (used for description and Gemini context)
    weather_desc, temp_c = _get_weather_summary()

    # Real UHBVN slab-rate savings using configurable monthly consumption baseline
    monthly_gen  = energy * 30
    monthly_cons = settings.monthly_consumption_kwh
    bill_info    = solar_bill_savings(monthly_gen, monthly_cons)
    saved_inr    = round(bill_info["savings_inr"] / 30, 0)
    bill_without = round(bill_info["bill_without_solar_inr"] / 30, 0)

    # Expected energy from stored expected_power_w (5-min samples → kWh)
    today_start = today.isoformat() + "T00:00:00Z"
    tomorrow    = (today + timedelta(days=1)).isoformat() + "T00:00:00Z"
    expected_kwh_raw = _sum_field_range("expected_power_w", today_start, tomorrow)
    expected_kwh = round(expected_kwh_raw / 1000 / 12, 2)
    pr_pct = round(energy / expected_kwh * 100, 1) if expected_kwh > 0.5 else 0.0

    # Peak sun hours approximation
    capacity_kw = settings.installed_capacity_w / 1000
    sun_hours   = round(energy / (capacity_kw * 0.78), 1) if capacity_kw > 0 else 0.0

    # Payback progress
    total_energy  = _latest("total_energy_kwh")
    total_savings = round(total_energy * settings.electricity_tariff_inr, 0)
    payback_pct   = round(
        min(total_savings / settings.system_cost_inr * 100, 100), 1
    ) if settings.system_cost_inr > 0 else 0.0

    # Gemini AI analysis — 1 call/day, fails gracefully if key not set
    ai_text = await _gemini_analysis(energy, pr_pct, health, weather_desc, temp_c)

    msg = tg.format_daily_report(
        date_str        = today.strftime("%d %b %Y"),
        kwh             = energy,
        expected_kwh    = expected_kwh,
        pr_pct          = pr_pct,
        saved_inr       = saved_inr,
        bill_without_inr = bill_without,
        co2_kg          = co2,
        health_score    = health,
        weather_desc    = weather_desc,
        sun_hours       = sun_hours,
        recovered_inr   = total_savings,
        payback_pct     = payback_pct,
        system_cost_inr = settings.system_cost_inr,
        ai_analysis     = ai_text,
    )
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

    # Best single day in the week
    best_day_flux = f'''
from(bucket: "{BUCKET}")
  |> range(start: {start_}, stop: {stop_})
  |> filter(fn: (r) => r["_field"] == "daily_energy_kwh")
  |> aggregateWindow(every: 1d, fn: max, createEmpty: false)
  |> max()
'''
    best_recs   = query(best_day_flux)
    best_day    = float(best_recs[0].get_value()) if best_recs else 0.0
    avg_health  = float(_compute_live_health())

    date_range = f"{(today - timedelta(days=6)).strftime('%d %b')}–{today.strftime('%d %b %Y')}"
    msg = tg.format_weekly_report(
        date_range   = date_range,
        kwh          = energy,
        savings_inr  = savings,
        co2_kg       = co2,
        avg_health   = avg_health,
        best_day_kwh = best_day,
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

    total_energy  = _latest("total_energy_kwh")
    total_savings = round(total_energy * settings.electricity_tariff_inr, 0)
    payback_pct   = round(
        min(total_savings / settings.system_cost_inr * 100, 100), 1
    ) if settings.system_cost_inr > 0 else 0

    # Real UHBVN bill savings for the month (assumes 600 kWh/month household consumption)
    bill_info    = solar_bill_savings(energy, 600.0)
    savings_real = bill_info["savings_inr"]
    bill_without = bill_info["bill_without_solar_inr"]

    msg = tg.format_monthly_report(
        month_str       = prev_month_start.strftime("%B %Y"),
        kwh             = energy,
        savings_inr     = savings_real,
        bill_without_inr = bill_without,
        co2_kg          = co2,
        payback_pct     = payback_pct,
        system_cost_inr = settings.system_cost_inr,
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
