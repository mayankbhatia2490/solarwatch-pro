"""
AI Solar Analyst — Gemini-powered daily analysis + event-based anomaly alerts.

This module is imported by solar_collector.py and provides:
1. Daily 7:00 AM analysis report emailed to you.
2. Real-time event-based anomaly detection (PV string failure, thermal throttle, grid trip).
3. Good-event notifications (e.g., best power day this month).
"""

import os
import json
import logging
import requests
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)

# --- Config (inherited from env vars) ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
INSTALLED_CAPACITY_W = float(os.environ.get("INSTALLED_CAPACITY_W", "3500"))
INFLUX_URL = os.environ.get("INFLUXDB_URL", "http://influxdb:8086")
INFLUX_TOKEN = os.environ.get("INFLUXDB_TOKEN", "")
INFLUX_ORG = os.environ.get("INFLUXDB_ORG", "solar")
INFLUX_BUCKET = os.environ.get("INFLUXDB_BUCKET", "solar_metrics")

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-1.5-flash:generateContent"

# --- Event Thresholds for real-time anomaly detection ---
THRESHOLDS = {
    # PV string voltage below 50V when output power > 100W suggests string issue
    "pv_voltage_low_threshold_v": 50.0,
    # Internal radiator temp above 80°C causes thermal throttle
    "radiator_temp_critical_c": 80.0,
    # Radiator temp warning
    "radiator_temp_warn_c": 70.0,
    # Grid frequency normal range: 49.5 - 50.5 Hz (India)
    "grid_freq_low": 49.3,
    "grid_freq_high": 50.7,
    # Grid voltage normal range: 200–260V single phase
    "grid_voltage_low_v": 200.0,
    "grid_voltage_high_v": 260.0,
    # Efficiency ratio: actual power / theoretical max. Below 50% on a sunny day = problem
    "pr_low_threshold_pct": 50.0,
}

# Track which events have fired to prevent repeat emails within same period
_event_cooldown = {}
EVENT_COOLDOWN_MINUTES = 30  # min time between same-type event emails


def _cooldown_ok(event_key):
    """Return True if we haven't fired this event recently."""
    last = _event_cooldown.get(event_key)
    if last is None:
        return True
    return (datetime.now() - last).total_seconds() > (EVENT_COOLDOWN_MINUTES * 60)


def _mark_event(event_key):
    _event_cooldown[event_key] = datetime.now()


# ─── InfluxDB Query Helper ────────────────────────────────────────────────────

def query_influx(flux_query):
    """Run a Flux query against InfluxDB and return rows as list of dicts."""
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
            logger.error(f"InfluxDB query failed: {r.status_code} {r.text[:300]}")
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


def get_daily_summary():
    """Query InfluxDB for yesterday's aggregated solar metrics."""
    yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    flux = f"""
from(bucket: "{INFLUX_BUCKET}")
  |> range(start: {yesterday}T00:00:00Z, stop: {yesterday}T23:59:59Z)
  |> filter(fn: (r) => r["_measurement"] == "solar_metrics")
  |> filter(fn: (r) => r["_field"] == "power_now_w" 
      or r["_field"] == "daily_energy_kwh" 
      or r["_field"] == "shortwave_radiation_wm2"
      or r["_field"] == "expected_power_w"
      or r["_field"] == "cloud_cover_pct"
      or r["_field"] == "internal_radiator_temperature"
      or r["_field"] == "internal_ambient_temperature"
      or r["_field"] == "grid_r_voltage"
      or r["_field"] == "grid_frequency"
      or r["_field"] == "pv1_voltage"
      or r["_field"] == "pv2_voltage"
      or r["_field"] == "avoidable_loss_flag")
  |> aggregateWindow(every: 1d, fn: mean)
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
    """
    rows = query_influx(flux)
    if not rows:
        return None

    # Also get max power and energy total today
    flux_max = f"""
from(bucket: "{INFLUX_BUCKET}")
  |> range(start: {yesterday}T00:00:00Z, stop: {yesterday}T23:59:59Z)
  |> filter(fn: (r) => r["_measurement"] == "solar_metrics")
  |> filter(fn: (r) => r["_field"] == "power_now_w" or r["_field"] == "daily_energy_kwh")
  |> aggregateWindow(every: 1d, fn: max)
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
    """
    max_rows = query_influx(flux_max)
    max_data = max_rows[0] if max_rows else {}

    data = rows[0] if rows else {}
    return {
        "date": yesterday,
        "avg_power_w": float(data.get("power_now_w", 0) or 0),
        "max_power_w": float(max_data.get("power_now_w", 0) or 0),
        "energy_today_kwh": float(max_data.get("daily_energy_kwh", 0) or 0),
        "avg_radiation_wm2": float(data.get("shortwave_radiation_wm2", 0) or 0),
        "avg_cloud_cover_pct": float(data.get("cloud_cover_pct", 0) or 0),
        "avg_expected_power_w": float(data.get("expected_power_w", 0) or 0),
        "avg_radiator_temp_c": float(data.get("internal_radiator_temperature", 0) or 0),
        "avg_pv1_voltage_v": float(data.get("pv1_voltage", 0) or 0),
        "avg_grid_voltage_v": float(data.get("grid_r_voltage", 0) or 0),
        "avg_grid_freq_hz": float(data.get("grid_frequency", 0) or 0),
        "avoidable_loss_events": int(float(data.get("avoidable_loss_flag", 0) or 0)),
    }


# ─── Gemini AI Call ───────────────────────────────────────────────────────────

def call_gemini(prompt):
    """Send a prompt to Gemini 1.5 Flash (free tier) and return text response."""
    if not GEMINI_API_KEY:
        logger.warning("GEMINI_API_KEY not set. Skipping AI analysis.")
        return None

    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 1500,
        }
    }
    try:
        r = requests.post(
            f"{GEMINI_URL}?key={GEMINI_API_KEY}",
            headers={"Content-Type": "application/json"},
            json=payload,
            timeout=30,
        )
        if r.status_code == 200:
            result = r.json()
            return result["candidates"][0]["content"]["parts"][0]["text"]
        else:
            logger.error(f"Gemini API error: {r.status_code} {r.text[:300]}")
            return None
    except Exception as e:
        logger.error(f"Gemini call exception: {e}")
        return None


# ─── Daily Report ─────────────────────────────────────────────────────────────

def build_daily_prompt(summary):
    """Build the prompt for Gemini daily analysis."""
    capacity_kw = INSTALLED_CAPACITY_W / 1000.0
    performance_ratio = (
        (summary["avg_power_w"] / summary["avg_expected_power_w"] * 100)
        if summary["avg_expected_power_w"] > 0 else 0
    )

    return f"""You are a solar energy monitoring assistant for a homeowner in Karnal, Haryana, India.
They have a {capacity_kw} kW rooftop solar system (3-phase inverter, 3 PV strings). 
Analyze yesterday's performance data and provide a clear, friendly daily report.

YESTERDAY'S DATA ({summary['date']}):
- Energy Generated: {summary['energy_today_kwh']:.2f} kWh
- Average Output Power: {summary['avg_power_w']:.0f} W
- Peak Output Power: {summary['max_power_w']:.0f} W
- Expected Power (based on solar radiation): {summary['avg_expected_power_w']:.0f} W
- Performance Ratio: {performance_ratio:.1f}%
- Average Solar Radiation: {summary['avg_radiation_wm2']:.0f} W/m²
- Average Cloud Cover: {summary['avg_cloud_cover_pct']:.0f}%
- Average Inverter Radiator Temperature: {summary['avg_radiator_temp_c']:.1f} °C
- Average PV1 String Voltage: {summary['avg_pv1_voltage_v']:.1f} V
- Average Grid Voltage: {summary['avg_grid_voltage_v']:.1f} V
- Average Grid Frequency: {summary['avg_grid_freq_hz']:.2f} Hz
- Avoidable Loss Events Detected: {summary['avoidable_loss_events']} occurrences

NORMAL REFERENCE VALUES (for Karnal, India):
- Expected PV string voltage: 200-450V
- Normal grid voltage: 220-240V
- Normal grid frequency: 49.5-50.5 Hz
- Acceptable radiator temperature: below 70°C
- Good performance ratio on sunny day: 70-85%

Please provide:
1. **Overall Grade** (A/B/C/D) for yesterday with 1-line reason
2. **What went well** (if anything)
3. **Issues or concerns** (if any parameter is outside normal range, explain what it means in simple terms)
4. **Action recommended** (if anything needs attention)
5. **Income estimate** at ₹6.5 per kWh for the day

Keep it under 300 words, use simple language, no technical jargon.
"""


def send_daily_ai_report(send_email_fn):
    """Fetch yesterday's data, run AI analysis, and email the report."""
    logger.info("Running daily AI analysis...")
    summary = get_daily_summary()

    if not summary:
        logger.warning("No InfluxDB data found for yesterday. Skipping daily report.")
        return

    prompt = build_daily_prompt(summary)
    ai_response = call_gemini(prompt)

    if not ai_response:
        # Fallback: send raw stats without AI
        ai_response = (
            f"(AI analysis unavailable — check GEMINI_API_KEY)\n\n"
            f"Yesterday's Stats:\n"
            f"  Energy: {summary['energy_today_kwh']:.2f} kWh\n"
            f"  Peak Power: {summary['max_power_w']:.0f} W\n"
            f"  Performance Ratio: {(summary['avg_power_w']/summary['avg_expected_power_w']*100 if summary['avg_expected_power_w'] else 0):.1f}%\n"
        )

    subject = f"☀️ Solar Daily Report — {summary['date']} | {summary['energy_today_kwh']:.1f} kWh"
    body = f"Solar System Daily Report\n{'='*40}\n\n{ai_response}"

    send_email_fn(subject, body)
    logger.info("Daily AI report sent.")


# ─── Real-Time Event Detection ────────────────────────────────────────────────

def check_realtime_events(solar, weather, send_email_fn):
    """
    Analyse current reading for anomalous events beyond the basic alarm checks.
    Sends immediate email alerts + asks Gemini for a brief diagnosis.

    solar dict keys (all available after collector patch):
      power_now_w, daily_energy_kwh, total_energy_kwh, status_code, extra_metrics
    extra_metrics keys (lower_snake):
      pv1_voltage, pv1_current, pv2_voltage, pv2_current,
      grid_r_voltage, grid_r_current, grid_s_voltage, grid_s_current,
      grid_t_voltage, grid_t_current,
      grid_frequency, bus_voltage,
      internal_ambient_temperature, internal_radiator_temperature
    weather keys:
      shortwave_radiation_wm2, cloud_cover_pct, temperature_c
    """
    em = solar.get("extra_metrics", {})
    events = []

    # 1. PV String Voltage abnormally low while inverter is generating power
    pv1_v = em.get("pv1_voltage", 0)
    pv2_v = em.get("pv2_voltage", 0)
    power = solar.get("power_now_w", 0)

    if power > 200 and pv1_v > 0 and pv1_v < THRESHOLDS["pv_voltage_low_threshold_v"]:
        if _cooldown_ok("pv1_low"):
            events.append({
                "key": "pv1_low",
                "severity": "WARNING",
                "title": "PV String 1 Low Voltage",
                "detail": f"PV1 voltage is {pv1_v:.1f}V (expected >150V). Possible heavy soiling, shading, or a failed panel in this string.",
                "data": f"PV1: {pv1_v}V, PV2: {pv2_v}V, Output Power: {power}W"
            })

    if power > 200 and pv2_v > 0 and pv2_v < THRESHOLDS["pv_voltage_low_threshold_v"]:
        if _cooldown_ok("pv2_low"):
            events.append({
                "key": "pv2_low",
                "severity": "WARNING",
                "title": "PV String 2 Low Voltage",
                "detail": f"PV2 voltage is {pv2_v:.1f}V (expected >150V). Possible heavy soiling, shading, or a failed panel in this string.",
                "data": f"PV1: {pv1_v}V, PV2: {pv2_v}V, Output Power: {power}W"
            })

    # 2. Thermal throttle / critical temperature
    rad_temp = em.get("internal_radiator_temperature", 0)
    if rad_temp > THRESHOLDS["radiator_temp_critical_c"]:
        if _cooldown_ok("temp_critical"):
            events.append({
                "key": "temp_critical",
                "severity": "CRITICAL",
                "title": "Inverter Overheating",
                "detail": f"Inverter radiator temperature is {rad_temp:.1f}°C (critical >80°C). The inverter may be power throttling and losing output. Ensure the inverter has adequate ventilation.",
                "data": f"Radiator Temp: {rad_temp}°C, Ambient Temp: {em.get('internal_ambient_temperature',0)}°C, Power: {power}W"
            })
    elif rad_temp > THRESHOLDS["radiator_temp_warn_c"]:
        if _cooldown_ok("temp_warn"):
            events.append({
                "key": "temp_warn",
                "severity": "WARNING",
                "title": "Inverter Running Hot",
                "detail": f"Inverter radiator temperature is {rad_temp:.1f}°C (warning >70°C). Check that the inverter room/area is well ventilated.",
                "data": f"Radiator Temp: {rad_temp}°C"
            })

    # 3. Grid frequency out of range
    freq = em.get("grid_frequency", 0)
    if freq > 0:
        if freq < THRESHOLDS["grid_freq_low"] or freq > THRESHOLDS["grid_freq_high"]:
            if _cooldown_ok("grid_freq"):
                events.append({
                    "key": "grid_freq",
                    "severity": "WARNING",
                    "title": "Grid Frequency Abnormal",
                    "detail": f"Grid frequency is {freq:.2f}Hz (normal: 49.3–50.7 Hz). This is a grid-side issue, not your solar system. The inverter may trip if it continues.",
                    "data": f"Grid Frequency: {freq}Hz, Power: {power}W"
                })

    # 4. Grid voltage abnormal
    grid_v = em.get("grid_r_voltage", 0)
    if grid_v > 0:
        if grid_v < THRESHOLDS["grid_voltage_low_v"]:
            if _cooldown_ok("grid_v_low"):
                events.append({
                    "key": "grid_v_low",
                    "severity": "WARNING",
                    "title": "Grid Voltage Too Low",
                    "detail": f"Grid R voltage is {grid_v:.1f}V (low, expected 220–240V). This is a grid issue. The inverter will disconnect to protect the system.",
                    "data": f"Grid R Voltage: {grid_v}V"
                })
        elif grid_v > THRESHOLDS["grid_voltage_high_v"]:
            if _cooldown_ok("grid_v_high"):
                events.append({
                    "key": "grid_v_high",
                    "severity": "WARNING",
                    "title": "Grid Voltage Too High",
                    "detail": f"Grid R voltage is {grid_v:.1f}V (high, expected 220–240V). This is a grid issue. High voltage can cause inverter trips or damage.",
                    "data": f"Grid R Voltage: {grid_v}V"
                })

    # 5. Good event: Today might be a record high production (simple heuristic)
    # If it's 2 PM and daily energy already exceeds 15 kWh, flag it as great day
    now = datetime.now()
    if now.hour == 14 and solar.get("daily_energy_kwh", 0) > 15.0:
        if _cooldown_ok("great_day"):
            events.append({
                "key": "great_day",
                "severity": "GOOD",
                "title": "🌟 Excellent Production Day!",
                "detail": f"Your system has already generated {solar['daily_energy_kwh']:.1f} kWh by 2 PM — this is shaping up to be an outstanding solar day!",
                "data": f"Energy so far: {solar['daily_energy_kwh']} kWh, Power: {power}W"
            })

    # Mark all event cooldowns first, then send ONE batched email + ONE Gemini call
    for event in events:
        _mark_event(event["key"])

    fire_batch_event_alert(events, weather, send_email_fn)



def fire_batch_event_alert(events, weather, send_email_fn):
    """
    Batch ALL triggered events into a single Gemini call and single email.
    This is the efficient approach for the free tier: 1 call regardless of how
    many events fire simultaneously.
    """
    if not events:
        return

    # Build a single compact prompt for all events
    event_lines = "\n".join(
        f"- [{e['severity']}] {e['title']}: {e['data']}" for e in events
    )

    ai_tip = ""
    if GEMINI_API_KEY:
        ai_prompt = f"""A solar monitoring system in Karnal, India (3.5 kW rooftop) has detected these events simultaneously:

{event_lines}

Context: Solar radiation={weather.get('shortwave_radiation_wm2', 0):.0f} W/m², Cloud cover={weather.get('cloud_cover_pct', 0):.0f}%

For each event, give 1-2 sentences: what it means and what the homeowner should do. Be simple, direct, no jargon.
Format as a bulleted list matching each event name.
"""
        ai_response = call_gemini(ai_prompt)
        if ai_response:
            ai_tip = f"\n\n🤖 AI Diagnosis:\n{ai_response.strip()}"

    # Determine the highest severity for subject line
    severity_order = {"CRITICAL": 3, "WARNING": 2, "GOOD": 1}
    top_severity = max(events, key=lambda e: severity_order.get(e["severity"], 0))["severity"]
    emoji = {"CRITICAL": "🚨", "WARNING": "⚠️", "GOOD": "🌟"}.get(top_severity, "ℹ️")

    titles = ", ".join(e["title"] for e in events)
    subject = f"{emoji} Solar Alert [{top_severity}]: {len(events)} Event(s) — {titles[:60]}"

    event_details = "\n\n".join(
        f"[{e['severity']}] {e['title']}\n  {e['detail']}\n  Data: {e['data']}"
        for e in events
    )

    body = (
        f"Solar Events Detected\n"
        f"{'='*40}\n"
        f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"{event_details}"
        f"{ai_tip}"
    )
    send_email_fn(subject, body)
    logger.info(f"Batch event alert sent: {len(events)} events [{top_severity}]")

