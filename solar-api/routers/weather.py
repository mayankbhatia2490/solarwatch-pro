from fastapi import APIRouter
from typing import Dict, Any
import httpx
import math
from datetime import datetime, timezone
from config import settings
from influx import query
from cal_utils import calibration_factor
import solcast

router = APIRouter(prefix="/api/weather", tags=["Weather"])

LAT        = float(settings.latitude)
LON        = float(settings.longitude)
CAPACITY_W = settings.installed_capacity_w

PANEL_TILT         = 5
PANEL_AZIMUTH      = 0
PERFORMANCE_RATIO  = 0.83
BIFACIAL_REAR_GAIN = 0.09
TEMP_COEFF         = -0.0030   # γ (Pmax): -0.30%/°C — Vikram HyperSol N-type
NOCT               = 45.0      # °C (IEC standard)


def _get_live_power() -> float:
    """15-minute mean of non-zero power readings — smooths Shinemonitor's noisy real-time field."""
    flux = f'''
from(bucket: "{settings.influxdb_bucket}")
  |> range(start: -15m)
  |> filter(fn: (r) => r["_field"] == "power_now_w")
  |> filter(fn: (r) => r["_value"] > 0)
  |> sort(columns: ["_time"])
'''
    recs = query(flux)
    if not recs:
        return 0.0
    vals = [float(r.get_value()) for r in recs]
    return sum(vals) / len(vals)


def _get_live_temp() -> float | None:
    """Return last inverter ambient temperature for NOCT correction."""
    flux = f'''
from(bucket: "{settings.influxdb_bucket}")
  |> range(start: -2h)
  |> filter(fn: (r) => r["_field"] == "temperature_2m")
  |> last()
'''
    recs = query(flux)
    return float(recs[0].get_value()) if recs else None


def _low_irr_factor(poa_wm2: float) -> float:
    """
    Inverter partial-load efficiency correction at low irradiance.
    String inverters lose ~5% per log10 decade below 1000 W/m² (IEA PVPS Task 13).
    Clamped to [0.75, 1.0] — even at very low light, we don't go below 75% of nominal PR.
    """
    if poa_wm2 <= 0:
        return 1.0
    return max(0.75, 1.0 + 0.05 * math.log10(poa_wm2 / 1000.0))


def _expected_power(poa_wm2: float, temp_c: float, month: int) -> int:
    """NOCT + temperature + low-irradiance-corrected expected power with calibration factor."""
    T_cell   = temp_c + (NOCT - 20.0) * (poa_wm2 / 800.0)
    t_corr   = 1 + TEMP_COEFF * (T_cell - 25.0)
    cal      = calibration_factor(month)
    pr_eff   = PERFORMANCE_RATIO * _low_irr_factor(poa_wm2)
    return round((poa_wm2 / 1000.0) * CAPACITY_W * (1 + BIFACIAL_REAR_GAIN) * pr_eff * t_corr * cal)


@router.get("")
async def get_weather() -> Dict[str, Any]:
    """
    Real-time weather and solar irradiance.
    Irradiance source priority:
      1. Solcast estimated_actuals (satellite-based, best for Indo-Gangetic haze)
      2. Open-Meteo global_tilted_irradiance (ERA5 reanalysis, good but misses fog)
    Open-Meteo still provides temperature, humidity, wind, rain.
    Expected power uses NOCT + temperature correction + low-irradiance PR correction + monthly cal.
    Actual power is the 15-minute mean of non-zero inverter readings.
    """
    current_month = datetime.now(timezone.utc).month
    actual_power_w = round(_get_live_power())

    # ── Fetch Open-Meteo (weather + irradiance backup) ────────────────────────
    om_data    = None
    om_current = {}
    om_hourly  = {}
    om_daily   = {}
    om_poa     = None

    try:
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={LAT}&longitude={LON}"
            f"&current=temperature_2m,relative_humidity_2m,cloud_cover,wind_speed_10m,"
            f"shortwave_radiation,apparent_temperature,precipitation"
            f"&hourly=temperature_2m,cloud_cover,global_tilted_irradiance,shortwave_radiation"
            f"&daily=sunrise,sunset,uv_index_max,precipitation_sum"
            f"&tilt={PANEL_TILT}&azimuth={PANEL_AZIMUTH}"
            f"&timezone=Asia%2FKolkata&forecast_days=3"
        )
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                om_data    = resp.json()
                om_current = om_data.get("current", {})
                om_hourly  = om_data.get("hourly", {})
                om_daily   = om_data.get("daily", {})

                ghi        = om_current.get("shortwave_radiation", 0) or 0
                now_iso    = om_current.get("time", "")[:13]
                h_times    = om_hourly.get("time", [])
                h_poa      = om_hourly.get("global_tilted_irradiance", [])
                om_poa     = ghi
                for i, t in enumerate(h_times):
                    if t.startswith(now_iso) and i < len(h_poa) and h_poa[i] is not None:
                        om_poa = h_poa[i]
                        break
    except Exception as e:
        print(f"Open-Meteo error: {e}")

    # ── Solcast irradiance (primary) — falls back to Open-Meteo if unavailable ─
    sc = solcast.get_current_irradiance()
    if sc and sc.get("gti_wm2", 0) > 0:
        poa_irradiance    = sc["gti_wm2"]
        irradiance_source = "solcast"
    elif om_poa is not None:
        poa_irradiance    = om_poa
        irradiance_source = "open-meteo"
    else:
        poa_irradiance    = None
        irradiance_source = "unavailable"

    # ── Expected power ────────────────────────────────────────────────────────
    temp_c = om_current.get("temperature_2m") or _get_live_temp() or 35.0
    if poa_irradiance is not None and poa_irradiance > 0:
        expected_power_w = _expected_power(poa_irradiance, temp_c, current_month)
        # Gap only shown above 15% capacity — below that the low-irradiance
        # correction is approximate and results are not actionable.
        efficiency_drop_pct = (
            round(max(0, (expected_power_w - actual_power_w) / expected_power_w * 100), 1)
            if expected_power_w > CAPACITY_W * 0.15 else None
        )
    else:
        expected_power_w    = None
        efficiency_drop_pct = None

    # ── Build response ────────────────────────────────────────────────────────
    if om_data:
        ghi = om_current.get("shortwave_radiation", 0) or 0
        return {
            "status": "success",
            "irradiance_source": irradiance_source,
            "solcast_calls_today": solcast.call_status(),
            "location": {
                "name":      settings.location_name,
                "latitude":  LAT,
                "longitude": LON,
                "timezone":  "Asia/Kolkata",
            },
            "data": {
                "current": {
                    "temperature_2m":       om_current.get("temperature_2m"),
                    "apparent_temperature": om_current.get("apparent_temperature"),
                    "relative_humidity_2m": om_current.get("relative_humidity_2m"),
                    "cloud_cover":          om_current.get("cloud_cover"),
                    "wind_speed_10m":       om_current.get("wind_speed_10m"),
                    "poa_irradiance_wm2":   poa_irradiance,
                    "shortwave_radiation":  ghi,
                    "precipitation":        om_current.get("precipitation", 0),
                },
                "hourly": {
                    "time":                     om_hourly.get("time", [])[:48],
                    "temperature_2m":           om_hourly.get("temperature_2m", [])[:48],
                    "cloud_cover":              om_hourly.get("cloud_cover", [])[:48],
                    "global_tilted_irradiance": om_hourly.get("global_tilted_irradiance", [])[:48],
                    "shortwave_radiation":      om_hourly.get("shortwave_radiation", [])[:48],
                },
                "daily": {
                    "sunrise":          om_daily.get("sunrise", [])[:3],
                    "sunset":           om_daily.get("sunset",  [])[:3],
                    "uv_index_max":     om_daily.get("uv_index_max", [])[:3],
                    "precipitation_sum":om_daily.get("precipitation_sum", [])[:3],
                },
                "solar_radiation_wm2": poa_irradiance,
                "expected_power_w":    expected_power_w,
                "actual_power_w":      actual_power_w,
                "efficiency_drop_pct": efficiency_drop_pct,
                "performance_ratio_used": round(PERFORMANCE_RATIO * _low_irr_factor(poa_irradiance or 1000), 3),
                "system_capacity_w":   CAPACITY_W,
                "irradiance_source":   irradiance_source,
            },
        }

    # ── Full fallback — Open-Meteo also failed ─────────────────────────────────
    return {
        "status": "weather_unavailable",
        "irradiance_source": irradiance_source,
        "location": {"name": settings.location_name, "latitude": LAT, "longitude": LON},
        "data": {
            "current": {
                "temperature_2m": None, "apparent_temperature": None,
                "relative_humidity_2m": None, "cloud_cover": None,
                "wind_speed_10m": None, "poa_irradiance_wm2": poa_irradiance,
                "shortwave_radiation": None, "precipitation": None,
            },
            "solar_radiation_wm2": poa_irradiance,
            "expected_power_w":    expected_power_w,
            "actual_power_w":      actual_power_w,
            "efficiency_drop_pct": efficiency_drop_pct,
            "performance_ratio_used": PERFORMANCE_RATIO,
            "system_capacity_w":   CAPACITY_W,
            "irradiance_source":   irradiance_source,
        },
    }
