"""
3-day production forecast.
Irradiance source priority:
  1. Solcast half-hourly forecasts (satellite-based, best for Indo-Gangetic haze)
  2. Open-Meteo global_tilted_irradiance (ERA5 reanalysis, good but misses fog)
Open-Meteo always fetched for temperature, cloud cover, sunrise/sunset, UV, rain.
"""
from fastapi import APIRouter, HTTPException
from typing import Dict, Any
import httpx
import math
from datetime import datetime, date, timedelta, timezone
from config import settings
from cal_utils import calibration_factor
import solcast

router = APIRouter(prefix="/api/forecast", tags=["Forecast"])

LAT        = float(settings.latitude)
LON        = float(settings.longitude)
CAPACITY_W = settings.installed_capacity_w

PANEL_TILT    = 5
PANEL_AZIMUTH = 0

PR                 = 0.83
TEMP_COEFF         = -0.0030
NOCT               = 45.0
BIFACIAL_REAR_GAIN = 0.09

_IST = timezone(timedelta(hours=5, minutes=30))


def _low_irr_factor(poa_wm2: float) -> float:
    """Inverter partial-load efficiency correction (IEA PVPS Task 13)."""
    if poa_wm2 <= 0:
        return 1.0
    return max(0.75, 1.0 + 0.05 * math.log10(poa_wm2 / 1000.0))


def _expected_power(poa_wm2: float, temp_c: float, month: int) -> float:
    T_cell = temp_c + (NOCT - 20.0) * (poa_wm2 / 800.0)
    correction = 1 + TEMP_COEFF * (T_cell - 25.0)
    cal = calibration_factor(month)
    pr_eff = PR * _low_irr_factor(poa_wm2)
    return max(0.0, (poa_wm2 / 1000.0) * CAPACITY_W * (1 + BIFACIAL_REAR_GAIN) * pr_eff * correction * cal)


def _build_sc_gti_map(sc_data: list[dict]) -> dict[str, float]:
    """
    Convert Solcast half-hourly forecast periods to IST-hour → avg GTI map.
    period_end is UTC; we attribute each 30-min block to the IST hour it starts in.
    Returns {"2025-05-16T14:00": 650.3, ...}
    """
    buckets: dict[str, list[float]] = {}
    for p in sc_data:
        try:
            pe_utc = datetime.fromisoformat(p["period_end"])
            if pe_utc.tzinfo is None:
                pe_utc = pe_utc.replace(tzinfo=timezone.utc)
            # period_end is the end; start = end - 30 min
            ps_ist = (pe_utc - timedelta(minutes=30)).astimezone(_IST)
            hour_key = ps_ist.strftime("%Y-%m-%dT%H:00")
            buckets.setdefault(hour_key, []).append(float(p.get("gti_wm2") or 0))
        except Exception:
            pass
    return {k: sum(v) / len(v) for k, v in buckets.items()}


@router.get("")
async def get_forecast() -> Dict[str, Any]:
    """
    Returns hourly production forecast for today + next 2 days.
    Uses Solcast GTI (satellite) as primary, Open-Meteo global_tilted_irradiance as fallback.
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
    om_poa = hourly.get("global_tilted_irradiance", [])

    # Solcast hourly GTI map (primary irradiance)
    sc_data = solcast.get_forecast()
    sc_gti  = _build_sc_gti_map(sc_data) if sc_data else {}

    hourly_forecast = []
    for i, t in enumerate(times):
        # Irradiance: Solcast preferred per hour, Open-Meteo fallback
        if t in sc_gti:
            irr_poa = sc_gti[t]
            hour_src = "solcast"
        else:
            irr_poa = (om_poa[i] or 0) if i < len(om_poa) else 0
            hour_src = "open-meteo"

        temp_c     = (temps[i] or 30.0) if i < len(temps) else 30.0
        slot_month = int(t[5:7]) if len(t) >= 7 else date.today().month
        power      = round(_expected_power(irr_poa, temp_c, slot_month))

        hourly_forecast.append({
            "time":             t,
            "expected_power_w": power,
            "irradiance_wm2":   round(irr_poa),
            "temperature_c":    temp_c,
            "cloud_cover_pct":  (clouds[i] or 0) if i < len(clouds) else 0,
            "irradiance_source": hour_src,
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
        interval_hours = 1.0
        kwh     = round(sum(h["expected_power_w"] * interval_hours for h in day_hours) / 1000, 2)
        savings = round(kwh * settings.electricity_tariff_inr, 1)
        label   = ["Today", "Tomorrow", day_date.strftime("%A")][d_idx]

        avg_cloud = (
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

        # Solcast data coverage for this day
        sc_hours = sum(1 for h in day_hours if h["irradiance_source"] == "solcast")
        day_src  = "solcast" if sc_hours > len(day_hours) // 2 else "open-meteo"

        daily_summaries.append({
            "date":              day_str,
            "label":             label,
            "expected_kwh":      kwh,
            "savings_inr":       savings,
            "avg_cloud_pct":     round(avg_cloud),
            "confidence_pct":    confidence,
            "irradiance_source": day_src,
            "sunrise":           sunrises[d_idx] if d_idx < len(sunrises) else None,
            "sunset":            sunsets[d_idx]  if d_idx < len(sunsets)  else None,
            "uv_index_max":      uv_max[d_idx]   if d_idx < len(uv_max)   else None,
            "precipitation_mm":  rain[d_idx]     if d_idx < len(rain)     else 0,
        })

    sc_hours_total = sum(1 for h in hourly_forecast if h["irradiance_source"] == "solcast")
    primary_source = "solcast" if sc_hours_total > 0 else "open-meteo"

    return {
        "status":              "success",
        "irradiance_source":   primary_source,
        "solcast_calls_today": solcast.call_status(),
        "system_capacity_w":   CAPACITY_W,
        "performance_ratio":   PR,
        "daily_summaries":     daily_summaries,
        "hourly_forecast":     hourly_forecast,
    }
