"""
Tomorrow's production forecast using Open-Meteo 3-day hourly data.
Uses the same temperature-corrected STC formula as the collector.
"""
from fastapi import APIRouter, HTTPException
from typing import Dict, Any
import httpx
from datetime import datetime, date, timedelta, timezone
from config import settings
from cal_utils import calibration_factor

router = APIRouter(prefix="/api/forecast", tags=["Forecast"])

LAT        = float(settings.latitude)
LON        = float(settings.longitude)
CAPACITY_W = settings.installed_capacity_w

# Panel geometry — 5.2° tilt, south-facing (measured on-site)
PANEL_TILT    = 5
PANEL_AZIMUTH = 0

# Vikram HyperSol N-type bifacial constants (matches collector)
PR                 = 0.83     # system PR for new N-type bifacial (wiring+inverter+mismatch)
TEMP_COEFF         = -0.0030  # γ (Pmax): -0.30%/°C — Vikram HyperSol N-type datasheet
NOCT               = 45.0     # °C (IEC standard)
BIFACIAL_REAR_GAIN = 0.09     # 9% rear irradiance at 5° tilt on concrete roof


def _expected_power(poa_wm2: float, temp_c: float, month: int) -> float:
    """
    Temperature-corrected STC formula — matches collector logic exactly.
    Uses POA (plane-of-array) irradiance and IEC NOCT cell temperature model.
    Applies monthly irradiance calibration factor from irradiance_cal.json.
    """
    T_cell = temp_c + (NOCT - 20.0) * (poa_wm2 / 800.0)
    correction = 1 + TEMP_COEFF * (T_cell - 25.0)
    cal = calibration_factor(month)
    return max(0.0, (poa_wm2 / 1000.0) * CAPACITY_W * (1 + BIFACIAL_REAR_GAIN) * PR * correction * cal)


@router.get("")
async def get_forecast() -> Dict[str, Any]:
    """
    Returns hourly production forecast for today + next 2 days.
    Uses global_tilted_irradiance (POA at 5°/south) from Open-Meteo.
    """
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={LAT}&longitude={LON}"
        f"&hourly=temperature_2m,cloud_cover,global_tilted_irradiance"
        f"&daily=sunrise,sunset,precipitation_sum,uv_index_max"
        f"&tilt={PANEL_TILT}&azimuth={PANEL_AZIMUTH}"
        f"&timezone=Asia%2FKolkata"
        f"&forecast_days=3"
    )

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            data = resp.json()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Open-Meteo unavailable: {e}")

    hourly = data.get("hourly", {})
    daily  = data.get("daily", {})
    times  = hourly.get("time", [])
    temps  = hourly.get("temperature_2m", [])
    clouds = hourly.get("cloud_cover", [])
    poa    = hourly.get("global_tilted_irradiance", [])

    hourly_forecast = []
    for i, t in enumerate(times):
        irr_poa = (poa[i] or 0) if i < len(poa) else 0
        temp_c  = (temps[i] or 30.0) if i < len(temps) else 30.0
        # Extract month from timestamp string "YYYY-MM-DDTHH:MM" for calibration
        slot_month = int(t[5:7]) if len(t) >= 7 else date.today().month
        power   = round(_expected_power(irr_poa, temp_c, slot_month))
        hourly_forecast.append({
            "time":             t,
            "expected_power_w": power,
            "irradiance_wm2":   round(irr_poa),
            "temperature_c":    temp_c,
            "cloud_cover_pct":  (clouds[i] or 0) if i < len(clouds) else 0,
        })

    daily_summaries = []
    today    = date.today()
    sunrises = daily.get("sunrise", [])
    sunsets  = daily.get("sunset",  [])
    uv_max   = daily.get("uv_index_max", [])
    rain     = daily.get("precipitation_sum", [])

    for d_idx in range(3):
        day_date  = today + timedelta(days=d_idx)
        day_str   = day_date.isoformat()
        day_hours = [h for h in hourly_forecast if h["time"].startswith(day_str)]
        # kWh = sum of hourly power (W) × interval (1h) / 1000; Open-Meteo is 1-hour slots
        interval_hours = 1.0
        kwh       = round(sum(h["expected_power_w"] * interval_hours for h in day_hours) / 1000, 2)
        savings   = round(kwh * settings.electricity_tariff_inr, 1)
        label     = ["Today", "Tomorrow", day_date.strftime("%A")][d_idx]

        avg_cloud  = (
            sum(h["cloud_cover_pct"] for h in day_hours) / len(day_hours)
            if day_hours else 50
        )
        # Tiered confidence by cloud cover quartile — IEA PVPS Task 16 heuristic
        if avg_cloud < 20:
            confidence = 90
        elif avg_cloud < 40:
            confidence = 75
        elif avg_cloud < 60:
            confidence = 60
        elif avg_cloud < 80:
            confidence = 45
        else:
            confidence = 30

        daily_summaries.append({
            "date":             day_str,
            "label":            label,
            "expected_kwh":     kwh,
            "savings_inr":      savings,
            "avg_cloud_pct":    round(avg_cloud),
            "confidence_pct":   confidence,
            "sunrise":          sunrises[d_idx] if d_idx < len(sunrises) else None,
            "sunset":           sunsets[d_idx]  if d_idx < len(sunsets)  else None,
            "uv_index_max":     uv_max[d_idx]   if d_idx < len(uv_max)   else None,
            "precipitation_mm": rain[d_idx]      if d_idx < len(rain)    else 0,
        })

    return {
        "status":            "success",
        "system_capacity_w": CAPACITY_W,
        "performance_ratio": PR,
        "daily_summaries":   daily_summaries,
        "hourly_forecast":   hourly_forecast,
    }
