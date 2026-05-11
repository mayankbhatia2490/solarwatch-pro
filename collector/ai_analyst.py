"""
AI Solar Analyst — Gemini-powered daily analysis + real-time event alerts.

1. Daily 7:00 AM analysis — event-aware (queries anomalous periods from InfluxDB).
2. Real-time event detection (PV string fault, thermal throttle, grid trip).
3. Good-event notifications.
4. KSY 5G-PRO+ fault code decoder.
5. Cooldown state persisted to disk — survives container restarts.
"""

import os
import json
import logging
import requests
from datetime import datetime, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

GEMINI_API_KEY       = os.environ.get("GEMINI_API_KEY", "")
INSTALLED_CAPACITY_W = float(os.environ.get("INSTALLED_CAPACITY_W", "3500"))
INFLUX_URL           = os.environ.get("INFLUXDB_URL", "http://influxdb:8086")
INFLUX_TOKEN         = os.environ.get("INFLUXDB_TOKEN", "")
INFLUX_ORG           = os.environ.get("INFLUXDB_ORG", "solar")
INFLUX_BUCKET        = os.environ.get("INFLUXDB_BUCKET", "solar_metrics")
ELECTRICITY_TARIFF   = float(os.environ.get("ELECTRICITY_TARIFF_INR", "6.5"))

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"

# Cooldown persistence path
COOLDOWN_FILE = Path("/app/data/event_cooldowns.json")
EVENT_COOLDOWN_MINUTES = 30

# ── Thresholds ────────────────────────────────────────────────────────────────
THRESHOLDS = {
    "pv_voltage_low_threshold_v":  50.0,
    "radiator_temp_critical_c":    85.0,
    "radiator_temp_warn_c":        75.0,
    "grid_freq_low":               49.3,
    "grid_freq_high":              50.7,
    "grid_voltage_low_v":          200.0,
    "grid_voltage_high_v":         260.0,
    "pr_low_threshold_pct":        50.0,
}

# ── KSY 5G-PRO+ fault code dictionary (from inverter manual) ─────────────────
KSY_FAULT_CODES: dict[str, dict] = {
    "F1":  {"title": "Grid Over-Voltage",     "severity": "warning",
            "detail": "AC grid voltage too high. Inverter disconnected to protect itself. Usually resolves automatically.",
            "action": "Monitor grid voltage. If recurring, contact UHBVN."},
    "F2":  {"title": "Grid Under-Voltage",    "severity": "warning",
            "detail": "AC grid voltage too low. Inverter disconnected for protection.",
            "action": "Monitor grid voltage. If power supply is irregular, contact your electricity provider."},
    "F3":  {"title": "Grid Over-Frequency",   "severity": "warning",
            "detail": "AC grid frequency above 50.5Hz. Grid-side issue.",
            "action": "No action needed — inverter reconnects automatically when frequency normalises."},
    "F4":  {"title": "Grid Under-Frequency",  "severity": "warning",
            "detail": "AC grid frequency below 49.5Hz. Grid-side issue.",
            "action": "No action needed — inverter reconnects automatically when frequency normalises."},
    "F5":  {"title": "Grid No-Voltage",       "severity": "critical",
            "detail": "No AC grid voltage detected. Grid power cut or main breaker tripped.",
            "action": "Check your main circuit breaker and grid supply. Contact UHBVN if power is out."},
    "F6":  {"title": "DC Input Over-Voltage", "severity": "critical",
            "detail": "PV string voltage too high. Can damage inverter MOSFET circuits.",
            "action": "Stop system immediately. Check PV string wiring. Do not restart until inspected by an engineer."},
    "F7":  {"title": "DC Bus Over-Voltage",   "severity": "critical",
            "detail": "Internal DC bus voltage too high. Possible MPPT or capacitor fault.",
            "action": "Power off inverter and contact KSY/your installer for diagnostics."},
    "F8":  {"title": "Inverter Overheating",  "severity": "critical",
            "detail": "Heatsink temperature exceeded safe limit. Inverter has shut down for self-protection.",
            "action": "Ensure inverter has adequate ventilation (30cm clearance all sides). Check if cooling fan is running. Do not restart until cool."},
    "F9":  {"title": "EEPROM Error",          "severity": "critical",
            "detail": "Internal memory fault detected. Firmware or hardware issue.",
            "action": "Power cycle the inverter. If error persists, contact KSY service centre."},
    "F10": {"title": "Relay Check Fault",     "severity": "warning",
            "detail": "Internal relay self-test failed. Inverter will retry automatically.",
            "action": "Monitor. If it persists for >2 hours, contact installer."},
    "F11": {"title": "DC Injection High",     "severity": "warning",
            "detail": "DC component in AC output exceeds safe limit. Transformer protection.",
            "action": "Contact your installer. May indicate grid-tie wiring issue."},
    "F12": {"title": "PV Insulation Fault",   "severity": "critical",
            "detail": "Insulation resistance between PV panels and earth is too low. Potential ground fault — safety hazard.",
            "action": "STOP SYSTEM IMMEDIATELY. Do not touch panels or cables. Contact qualified electrician."},
}

def decode_fault(code: str | None) -> dict | None:
    """Return human-readable fault info for a KSY fault code, or None if no fault."""
    if not code:
        return None
    code = code.strip().upper()
    return KSY_FAULT_CODES.get(code)


# ── Cooldown persistence ──────────────────────────────────────────────────────

def _load_cooldowns() -> dict:
    try:
        if COOLDOWN_FILE.exists():
            data = json.loads(COOLDOWN_FILE.read_text())
            return {k: datetime.fromisoformat(v) for k, v in data.items()}
    except Exception:
        pass
    return {}

def _save_cooldowns(cooldowns: dict):
    try:
        COOLDOWN_FILE.parent.mkdir(parents=True, exist_ok=True)
        COOLDOWN_FILE.write_text(
            json.dumps({k: v.isoformat() for k, v in cooldowns.items()}, indent=2)
        )
    except Exception as e:
        logger.warning(f"Could not save cooldowns: {e}")

# Load on module import
_event_cooldown = _load_cooldowns()

def _cooldown_ok(event_key: str) -> bool:
    last = _event_cooldown.get(event_key)
    if last is None:
        return True
    return (datetime.now() - last).total_seconds() > (EVENT_COOLDOWN_MINUTES * 60)

def _mark_event(event_key: str):
    _event_cooldown[event_key] = datetime.now()
    _save_cooldowns(_event_cooldown)


# ── InfluxDB query helper ─────────────────────────────────────────────────────

def query_influx(flux_query: str) -> list[dict]:
    try:
        r = requests.post(
            f"{INFLUX_URL}/api/v2/query?org={INFLUX_ORG}",
            headers={
                "Authorization": f"Token {INFLUX_TOKEN}",
                "Content-Type": "application/vnd.flux",
                "Accept": "application/csv",
            },
            data=flux_query,
            timeout=30,
        )
        if r.status_code != 200:
            logger.error(f"InfluxDB query failed: {r.status_code}")
            return []

        rows = []
        lines = r.text.strip().split("\n")
        if len(lines) < 2:
            return []

        headers = [h.strip() for h in lines[0].split(",")]
        for line in lines[1:]:
            if not line.strip() or line.startswith("#"):
                continue
            values = [v.strip() for v in line.split(",")]
            if len(values) == len(headers):
                rows.append(dict(zip(headers, values)))
        return rows
    except Exception as e:
        logger.error(f"InfluxDB query exception: {e}")
        return []


def get_daily_summary() -> dict | None:
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    flux = f'''
from(bucket: "{INFLUX_BUCKET}")
  |> range(start: {yesterday}T00:00:00Z, stop: {yesterday}T23:59:59Z)
  |> filter(fn: (r) => r["_measurement"] == "solar_metrics")
  |> filter(fn: (r) =>
      r["_field"] == "power_now_w" or
      r["_field"] == "daily_energy_kwh" or
      r["_field"] == "shortwave_radiation_wm2" or
      r["_field"] == "expected_power_w" or
      r["_field"] == "cloud_cover_pct" or
      r["_field"] == "internal_radiator_temperature" or
      r["_field"] == "internal_ambient_temperature" or
      r["_field"] == "grid_r_voltage" or
      r["_field"] == "grid_frequency" or
      r["_field"] == "pv1_voltage" or
      r["_field"] == "pv2_voltage" or
      r["_field"] == "avoidable_loss_flag" or
      r["_field"] == "loss_inr_interval" or
      r["_field"] == "health_score")
  |> aggregateWindow(every: 1d, fn: mean)
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
'''
    rows = query_influx(flux)

    flux_max = f'''
from(bucket: "{INFLUX_BUCKET}")
  |> range(start: {yesterday}T00:00:00Z, stop: {yesterday}T23:59:59Z)
  |> filter(fn: (r) => r["_measurement"] == "solar_metrics")
  |> filter(fn: (r) => r["_field"] == "power_now_w" or r["_field"] == "daily_energy_kwh")
  |> aggregateWindow(every: 1d, fn: max)
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
'''
    max_rows = query_influx(flux_max)
    max_data = max_rows[0] if max_rows else {}
    data     = rows[0] if rows else {}

    if not data:
        return None

    # Total rupees lost to avoidable events yesterday
    flux_loss = f'''
from(bucket: "{INFLUX_BUCKET}")
  |> range(start: {yesterday}T00:00:00Z, stop: {yesterday}T23:59:59Z)
  |> filter(fn: (r) => r["_field"] == "loss_inr_interval")
  |> sum()
'''
    loss_rows = query_influx(flux_loss)
    total_loss_inr = float(loss_rows[0].get("_value", 0)) if loss_rows else 0

    return {
        "date":                    yesterday,
        "avg_power_w":             float(data.get("power_now_w", 0) or 0),
        "max_power_w":             float(max_data.get("power_now_w", 0) or 0),
        "energy_today_kwh":        float(max_data.get("daily_energy_kwh", 0) or 0),
        "avg_radiation_wm2":       float(data.get("shortwave_radiation_wm2", 0) or 0),
        "avg_cloud_cover_pct":     float(data.get("cloud_cover_pct", 0) or 0),
        "avg_expected_power_w":    float(data.get("expected_power_w", 0) or 0),
        "avg_radiator_temp_c":     float(data.get("internal_radiator_temperature", 0) or 0),
        "avg_pv1_voltage_v":       float(data.get("pv1_voltage", 0) or 0),
        "avg_grid_voltage_v":      float(data.get("grid_r_voltage", 0) or 0),
        "avg_grid_freq_hz":        float(data.get("grid_frequency", 0) or 0),
        "avoidable_loss_events":   int(float(data.get("avoidable_loss_flag", 0) or 0)),
        "total_loss_inr":          round(total_loss_inr, 1),
        "avg_health_score":        round(float(data.get("health_score", 0) or 0), 0),
    }


def get_anomalous_periods(yesterday: str) -> list[dict]:
    """
    Query InfluxDB for specific time windows where performance was abnormal.
    Returns a list of events for inclusion in the AI prompt.
    """
    # Find 1-hour windows where actual < 40% of expected (with enough radiation)
    flux = f'''
from(bucket: "{INFLUX_BUCKET}")
  |> range(start: {yesterday}T00:00:00Z, stop: {yesterday}T23:59:59Z)
  |> filter(fn: (r) =>
      r["_field"] == "power_now_w" or
      r["_field"] == "expected_power_w" or
      r["_field"] == "shortwave_radiation_wm2" or
      r["_field"] == "internal_radiator_temperature")
  |> aggregateWindow(every: 1h, fn: mean, createEmpty: false)
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
'''
    rows = query_influx(flux)
    events = []
    for row in rows:
        hour    = row.get("_time", "")[:16].replace("T", " ")
        power   = float(row.get("power_now_w", 0) or 0)
        exp     = float(row.get("expected_power_w", 0) or 0)
        rad     = float(row.get("shortwave_radiation_wm2", 0) or 0)
        temp    = float(row.get("internal_radiator_temperature", 0) or 0)

        if exp > 200 and rad > 300:
            eff = power / exp
            if eff < 0.40:
                lost_inr = round((exp - power) / 1000 * ELECTRICITY_TARIFF, 1)
                events.append(
                    f"  {hour}: Output {power:.0f}W vs {exp:.0f}W expected "
                    f"({eff*100:.0f}% efficiency, radiation {rad:.0f} W/m²) "
                    f"— ₹{lost_inr} lost"
                )

        if temp > 70:
            events.append(f"  {hour}: Heatsink temperature {temp:.1f}°C (warning >75°C)")

    return events


# ── Gemini API ────────────────────────────────────────────────────────────────

def call_gemini(prompt: str) -> str | None:
    if not GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY not set. Skipping AI analysis.")
        return None
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.3, "maxOutputTokens": 1500},
    }
    try:
        r = requests.post(
            f"{GEMINI_URL}?key={GEMINI_API_KEY}",
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=30,
        )
        if r.status_code == 200:
            return r.json()["candidates"][0]["content"]["parts"][0]["text"]
        else:
            logger.error(f"Gemini API error: {r.status_code}")
            return None
    except Exception as e:
        logger.error(f"Gemini call exception: {e}")
        return None


# ── Daily report ──────────────────────────────────────────────────────────────

def build_daily_prompt(summary: dict, anomalous_periods: list[str]) -> str:
    capacity_kw = INSTALLED_CAPACITY_W / 1000.0
    perf_ratio = (
        (summary["avg_power_w"] / summary["avg_expected_power_w"] * 100)
        if summary["avg_expected_power_w"] > 0 else 0
    )
    income = round(summary["energy_today_kwh"] * ELECTRICITY_TARIFF, 1)

    periods_block = (
        "\n".join(anomalous_periods)
        if anomalous_periods
        else "  No significant underperformance detected."
    )

    return f"""You are a solar energy monitoring assistant for a homeowner in Karnal, Haryana, India.
They have a {capacity_kw}kW rooftop solar system (KSY 5G-PRO+ inverter).

YESTERDAY'S PERFORMANCE ({summary['date']}):
- Energy Generated: {summary['energy_today_kwh']:.2f} kWh (income: ₹{income})
- Average Output: {summary['avg_power_w']:.0f}W | Peak: {summary['max_power_w']:.0f}W
- Expected Power: {summary['avg_expected_power_w']:.0f}W | Performance Ratio: {perf_ratio:.1f}%
- Avoidable Loss: ₹{summary['total_loss_inr']} (due to system underperformance on clear periods)
- Avg Solar Radiation: {summary['avg_radiation_wm2']:.0f} W/m² | Cloud Cover: {summary['avg_cloud_cover_pct']:.0f}%
- Inverter Heatsink: {summary['avg_radiator_temp_c']:.1f}°C avg
- PV1 Voltage: {summary['avg_pv1_voltage_v']:.1f}V avg
- Grid Voltage: {summary['avg_grid_voltage_v']:.1f}V | Frequency: {summary['avg_grid_freq_hz']:.2f}Hz
- System Health Score: {summary['avg_health_score']:.0f}/100

SPECIFIC UNDERPERFORMANCE WINDOWS DETECTED YESTERDAY:
{periods_block}

NORMAL REFERENCE VALUES:
- Grid voltage: 220–240V | Frequency: 49.5–50.5Hz
- PV string voltage: 200–450V
- Heatsink temperature: below 75°C is normal; 75–85°C = warn; >85°C = critical
- Good performance ratio on sunny day: 70–85%

Please provide:
1. **Overall Grade** (A/B/C/D) for yesterday with 1-line reason
2. **What went well** (if anything)
3. **Specific issues** (reference the exact time windows above if relevant)
4. **One clear action** the homeowner should take today (if anything)
5. **Income for the day**: ₹{income}

Keep it under 250 words, simple language, no jargon.
"""


def send_daily_ai_report(send_email_fn):
    logger.info("Running daily AI analysis...")
    summary = get_daily_summary()
    if not summary:
        logger.warning("No InfluxDB data for yesterday. Skipping daily report.")
        return

    anomalous_periods = get_anomalous_periods(summary["date"])
    prompt      = build_daily_prompt(summary, anomalous_periods)
    ai_response = call_gemini(prompt)

    if not ai_response:
        pr = (
            summary["avg_power_w"] / summary["avg_expected_power_w"] * 100
            if summary["avg_expected_power_w"] else 0
        )
        ai_response = (
            f"(AI unavailable — check GEMINI_API_KEY)\n\n"
            f"Yesterday's Stats:\n"
            f"  Energy: {summary['energy_today_kwh']:.2f} kWh\n"
            f"  Peak Power: {summary['max_power_w']:.0f}W\n"
            f"  Performance Ratio: {pr:.1f}%\n"
            f"  Avoidable Loss: ₹{summary['total_loss_inr']}\n"
            f"  Health Score: {summary['avg_health_score']:.0f}/100\n"
        )

    subject = f"☀️ Solar Daily Report — {summary['date']} | {summary['energy_today_kwh']:.1f} kWh | ₹{round(summary['energy_today_kwh'] * ELECTRICITY_TARIFF, 0):.0f} saved"
    body    = f"Solar System Daily Report\n{'='*40}\n\n{ai_response}"
    send_email_fn(subject, body)
    logger.info("Daily AI report sent.")


# ── Real-time event detection ─────────────────────────────────────────────────

def check_realtime_events(solar: dict, weather: dict, send_email_fn):
    em     = solar.get("extra_metrics", {})
    events = []
    power  = solar.get("power_now_w", 0)

    # 0. Fault code — always decode and alert regardless of other checks
    fault_info = decode_fault(solar.get("fault_code"))
    if fault_info and _cooldown_ok(f"fault_{solar.get('fault_code')}"):
        events.append({
            "key":      f"fault_{solar.get('fault_code')}",
            "severity": fault_info["severity"].upper(),
            "title":    f"Inverter Fault: {fault_info['title']}",
            "detail":   fault_info["detail"],
            "data":     f"Fault Code: {solar.get('fault_code')}, Power: {power}W",
            "action":   fault_info["action"],
        })

    # 1. PV string voltage low while generating
    pv1_v = em.get("pv1_voltage", 0)
    pv2_v = em.get("pv2_voltage", 0)
    if power > 200 and pv1_v > 0 and pv1_v < THRESHOLDS["pv_voltage_low_threshold_v"]:
        if _cooldown_ok("pv1_low"):
            events.append({
                "key": "pv1_low", "severity": "WARNING",
                "title": "PV String 1 Low Voltage",
                "detail": f"PV1 at {pv1_v:.1f}V while inverter generates {power}W. Possible soiling, shading, or failed panel.",
                "data": f"PV1: {pv1_v}V, PV2: {pv2_v}V, Power: {power}W",
            })
    if power > 200 and pv2_v > 0 and pv2_v < THRESHOLDS["pv_voltage_low_threshold_v"]:
        if _cooldown_ok("pv2_low"):
            events.append({
                "key": "pv2_low", "severity": "WARNING",
                "title": "PV String 2 Low Voltage",
                "detail": f"PV2 at {pv2_v:.1f}V while inverter generates {power}W.",
                "data": f"PV1: {pv1_v}V, PV2: {pv2_v}V, Power: {power}W",
            })

    # 2. Thermal
    rad_temp = em.get("internal_radiator_temperature", 0)
    if rad_temp > THRESHOLDS["radiator_temp_critical_c"]:
        if _cooldown_ok("temp_critical"):
            events.append({
                "key": "temp_critical", "severity": "CRITICAL",
                "title": "Inverter Overheating (F8 Risk)",
                "detail": f"Heatsink {rad_temp:.1f}°C — above critical {THRESHOLDS['radiator_temp_critical_c']}°C. Inverter may shut down.",
                "data": f"Heatsink: {rad_temp}°C, Ambient: {em.get('internal_ambient_temperature',0)}°C, Power: {power}W",
            })
    elif rad_temp > THRESHOLDS["radiator_temp_warn_c"]:
        if _cooldown_ok("temp_warn"):
            events.append({
                "key": "temp_warn", "severity": "WARNING",
                "title": "Inverter Running Hot",
                "detail": f"Heatsink {rad_temp:.1f}°C — above warn {THRESHOLDS['radiator_temp_warn_c']}°C. Ensure ventilation.",
                "data": f"Heatsink: {rad_temp}°C",
            })

    # 3. Grid frequency
    freq = em.get("grid_frequency", 0)
    if freq > 0 and (freq < THRESHOLDS["grid_freq_low"] or freq > THRESHOLDS["grid_freq_high"]):
        if _cooldown_ok("grid_freq"):
            events.append({
                "key": "grid_freq", "severity": "WARNING",
                "title": "Grid Frequency Abnormal",
                "detail": f"Grid frequency {freq:.2f}Hz (normal 49.3–50.7Hz). Grid-side issue — inverter may trip.",
                "data": f"Frequency: {freq}Hz",
            })

    # 4. Grid voltage
    grid_v = em.get("grid_r_voltage", 0)
    if grid_v > 0:
        if grid_v < THRESHOLDS["grid_voltage_low_v"]:
            if _cooldown_ok("grid_v_low"):
                events.append({
                    "key": "grid_v_low", "severity": "WARNING",
                    "title": "Grid Voltage Too Low",
                    "detail": f"Grid R-phase {grid_v:.1f}V (below 200V). Inverter will disconnect.",
                    "data": f"Grid R: {grid_v}V",
                })
        elif grid_v > THRESHOLDS["grid_voltage_high_v"]:
            if _cooldown_ok("grid_v_high"):
                events.append({
                    "key": "grid_v_high", "severity": "WARNING",
                    "title": "Grid Voltage Too High",
                    "detail": f"Grid R-phase {grid_v:.1f}V (above 260V). High voltage can damage equipment.",
                    "data": f"Grid R: {grid_v}V",
                })

    # 5. Great production day (2PM check)
    now = datetime.now()
    if now.hour == 14 and solar.get("daily_energy_kwh", 0) > 15.0:
        if _cooldown_ok("great_day"):
            events.append({
                "key": "great_day", "severity": "GOOD",
                "title": "🌟 Outstanding Production Day!",
                "detail": f"Already {solar['daily_energy_kwh']:.1f} kWh by 2PM — excellent solar day.",
                "data": f"Energy so far: {solar['daily_energy_kwh']} kWh",
            })

    for event in events:
        _mark_event(event["key"])

    fire_batch_event_alert(events, weather, send_email_fn)


def fire_batch_event_alert(events: list, weather: dict, send_email_fn):
    if not events:
        return

    event_lines = "\n".join(
        f"- [{e['severity']}] {e['title']}: {e['data']}" for e in events
    )

    ai_tip = ""
    if GEMINI_API_KEY:
        ai_prompt = f"""A {INSTALLED_CAPACITY_W/1000:.1f}kW solar system in Karnal, India detected these events:

{event_lines}

Weather: Radiation={weather.get('shortwave_radiation_wm2', 0):.0f} W/m², Cloud={weather.get('cloud_cover_pct', 0):.0f}%

For each event, give 1-2 sentences: what it means and the single most important thing the homeowner should do right now.
Format as a bulleted list. Simple language, no technical jargon.
"""
        ai_response = call_gemini(ai_prompt)
        if ai_response:
            ai_tip = f"\n\n🤖 AI Diagnosis:\n{ai_response.strip()}"

    severity_order = {"CRITICAL": 3, "WARNING": 2, "GOOD": 1}
    top = max(events, key=lambda e: severity_order.get(e["severity"], 0))["severity"]
    emoji = {"CRITICAL": "🚨", "WARNING": "⚠️", "GOOD": "🌟"}.get(top, "ℹ️")

    titles   = ", ".join(e["title"] for e in events)
    subject  = f"{emoji} Solar Alert [{top}]: {titles[:60]}"

    details = "\n\n".join(
        f"[{e['severity']}] {e['title']}\n  {e['detail']}\n  Data: {e['data']}"
        for e in events
    )
    body = (
        f"Solar Events Detected\n{'='*40}\n"
        f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"{details}"
        f"{ai_tip}"
    )
    send_email_fn(subject, body)
    logger.info(f"Batch event alert: {len(events)} events [{top}]")
