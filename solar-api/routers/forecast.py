"""
Tomorrow's production forecast using Open-Meteo 3-day hourly data.
Uses the same temperature-corrected STC formula as the collector.
"""
from fastapi import APIRouter, HTTPException
from typing import Dict, Any
import httpx
from datetime import datetime, date, timedelta, timezone
from config import settings

router = APIRouter(prefix="/api/forecast", tags=["Forecast"])

LAT          = float(settings.latitude)
LON          = float(settings.longitude)
CAPACITY_W   = settings.installed_capacity_w
PR           = 0.78    # India performance ratio
TEMP_COEFF   = -0.0039 # KSY 5G-PRO+ temperature coefficient /°C


def _expected_power(irradiance_wm2: float, temp_c: float) -> float:
    """Temperature-corrected STC formula (matches collector logic exactly)."""
    T_cell = temp_c + 25.0
    correction = 1 + TEMP_COEFF * (T_cell - 25.0)
    return max(0.0, (irradiance_wm2 / 1000.0) * CAPACITY_W * PR * correction)


@router.get("/")
async def get_forecast() -> Dict[str, Any]:
    """
    Returns hourly production forecast for today + next 2 days.
    Each hour shows: expected power (W), irradiance (W/m²), temperature (°C),
    cloud cover (%), and daily summary totals.
    """
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={LAT}&longitude={LON}"
        f"&hourly=temperature_2m,cloud_cover,direct_radiation,diffuse_radiation"
        f"&daily=sunrise,sunset,precipitation_sum,uv_index_max"
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

    hourly  = data.get("hourly", {})
    daily   = data.get("daily", {})
    times   = hourly.get("time", [])
    temps   = hourly.get("temperature_2m", [])
    clouds  = hourly.get("cloud_cover", [])
    direct  = hourly.get("direct_radiation", [])
    diffuse = hourly.get("diffuse_radiation", [])

    hourly_forecast = []
    for i, t in enumerate(times):
        irr    = (direct[i] or 0) + (diffuse[i] or 0)
        temp_c = temps[i] or 30.0
        power  = round(_expected_power(irr, temp_c))
        hourly_forecast.append({
            "time":             t,
            "expected_power_w": power,
            "irradiance_wm2":   round(irr),
            "temperature_c":    temp_c,
            "cloud_cover_pct":  clouds[i] or 0,
        })

    # Build daily summaries (kWh = sum of hourly W / 1000)
    daily_summaries = []
    today = date.today()
    sunrises = daily.get("sunrise", [])
    sunsets  = daily.get("sunset",  [])
    uv_max   = daily.get("uv_index_max", [])
    rain     = daily.get("precipitation_sum", [])

    for d_idx in range(3):
        day_date = today + timedelta(days=d_idx)
        day_str  = day_date.isoformat()
        day_hours = [h for h in hourly_forecast if h["time"].startswith(day_str)]
        kwh = round(sum(h["expected_power_w"] for h in day_hours) / 1000, 2)
        savings = round(kwh * settings.electricity_tariff_inr, 1)
        label = ["Today", "Tomorrow", day_date.strftime("%A")][d_idx]

        # Confidence: reduce if cloud cover is high
        avg_cloud = (
            sum(h["cloud_cover_pct"] for h in day_hours) / len(day_hours)
            if day_hours else 50
        )
        confidence = max(40, round(100 - avg_cloud * 0.6))

        daily_summaries.append({
            "date":              day_str,
            "label":             label,
            "expected_kwh":      kwh,
            "savings_inr":       savings,
            "avg_cloud_pct":     round(avg_cloud),
            "confidence_pct":    confidence,
            "sunrise":           sunrises[d_idx] if d_idx < len(sunrises) else None,
            "sunset":            sunsets[d_idx]  if d_idx < len(sunsets)  else None,
            "uv_index_max":      uv_max[d_idx]   if d_idx < len(uv_max)   else None,
            "precipitation_mm":  rain[d_idx]     if d_idx < len(rain)     else 0,
        })

    return {
        "status":          "success",
        "system_capacity_w": CAPACITY_W,
        "performance_ratio": PR,
        "daily_summaries": daily_summaries,
        "hourly_forecast": hourly_forecast,
    }
