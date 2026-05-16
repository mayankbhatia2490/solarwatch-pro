from fastapi import APIRouter
from typing import Dict, Any
import httpx
from datetime import datetime, timezone
from config import settings
from influx import query
from cal_utils import calibration_factor

router = APIRouter(prefix="/api/weather", tags=["Weather"])

LAT        = float(settings.latitude)
LON        = float(settings.longitude)
CAPACITY_W = settings.installed_capacity_w

PANEL_TILT    = 5
PANEL_AZIMUTH = 0
PERFORMANCE_RATIO  = 0.83
BIFACIAL_REAR_GAIN = 0.09


def _get_live_power() -> float:
    bucket = settings.influxdb_bucket
    flux = f'''
from(bucket: "{bucket}")
  |> range(start: -2h)
  |> filter(fn: (r) => r["_field"] == "power_now_w")
  |> last()
'''
    recs = query(flux)
    return float(recs[0].get_value()) if recs else 0.0


@router.get("")
async def get_weather() -> Dict[str, Any]:
    """
    Fetches real-time weather from Open-Meteo for Karnal, Haryana.
    Uses global_tilted_irradiance (POA at 5° tilt, south-facing) for expected power.
    PR=0.83 for new N-type bifacial Vikram HyperSol panels.
    """
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={LAT}&longitude={LON}"
        f"&current=temperature_2m,relative_humidity_2m,cloud_cover,wind_speed_10m,"
        f"shortwave_radiation,apparent_temperature,precipitation"
        f"&hourly=temperature_2m,cloud_cover,global_tilted_irradiance,shortwave_radiation"
        f"&daily=sunrise,sunset,uv_index_max,precipitation_sum"
        f"&tilt={PANEL_TILT}&azimuth={PANEL_AZIMUTH}"
        f"&timezone=Asia%2FKolkata"
        f"&forecast_days=3"
    )

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                current = data.get("current", {})

                ghi = current.get("shortwave_radiation", 0) or 0

                # Extract POA for current hour from hourly data (global_tilted_irradiance
                # is only available in hourly, not in current endpoint)
                now_iso  = current.get("time", "")[:13]   # "YYYY-MM-DDTHH"
                hourly   = data.get("hourly", {})
                h_times  = hourly.get("time", [])
                h_poa    = hourly.get("global_tilted_irradiance", [])
                poa_irradiance = ghi  # fallback to GHI
                for i, t in enumerate(h_times):
                    if t.startswith(now_iso) and i < len(h_poa) and h_poa[i] is not None:
                        poa_irradiance = h_poa[i]
                        break

                # Expected power: POA × capacity × bifacial gain × PR × calibration factor
                current_month = datetime.now(timezone.utc).month
                cal_factor    = calibration_factor(current_month)
                expected_power_w = round(
                    (poa_irradiance / 1000.0) * CAPACITY_W * (1 + BIFACIAL_REAR_GAIN) * PERFORMANCE_RATIO * cal_factor
                )

                actual_power_w = round(_get_live_power())

                efficiency_drop_pct = 0.0
                if expected_power_w > 100:
                    efficiency_drop_pct = round(
                        max(0, (expected_power_w - actual_power_w) / expected_power_w * 100), 1
                    )

                hourly = data.get("hourly", {})
                daily  = data.get("daily", {})

                return {
                    "status": "success",
                    "location": {
                        "name":      settings.location_name,
                        "latitude":  LAT,
                        "longitude": LON,
                        "timezone":  "Asia/Kolkata"
                    },
                    "data": {
                        "current": {
                            "temperature_2m":       current.get("temperature_2m"),
                            "apparent_temperature": current.get("apparent_temperature"),
                            "relative_humidity_2m": current.get("relative_humidity_2m"),
                            "cloud_cover":          current.get("cloud_cover"),
                            "wind_speed_10m":       current.get("wind_speed_10m"),
                            "poa_irradiance_wm2":   poa_irradiance,
                            "shortwave_radiation":  ghi,
                            "precipitation":        current.get("precipitation", 0),
                        },
                        "hourly": {
                            "time":                    hourly.get("time", [])[:48],
                            "temperature_2m":          hourly.get("temperature_2m", [])[:48],
                            "cloud_cover":             hourly.get("cloud_cover", [])[:48],
                            "global_tilted_irradiance":hourly.get("global_tilted_irradiance", [])[:48],
                            "shortwave_radiation":     hourly.get("shortwave_radiation", [])[:48],
                        },
                        "daily": {
                            "sunrise":          daily.get("sunrise", [])[:3],
                            "sunset":           daily.get("sunset",  [])[:3],
                            "uv_index_max":     daily.get("uv_index_max", [])[:3],
                            "precipitation_sum":daily.get("precipitation_sum", [])[:3],
                        },
                        "solar_radiation_wm2": poa_irradiance,   # kept for WeatherPill compatibility
                        "expected_power_w":    expected_power_w,
                        "actual_power_w":      actual_power_w,
                        "efficiency_drop_pct": efficiency_drop_pct,
                        "performance_ratio_used": PERFORMANCE_RATIO,
                        "system_capacity_w":   CAPACITY_W,
                    }
                }
    except Exception as e:
        print(f"Weather API error: {e}")

    # Fallback — real InfluxDB power only; weather unavailable, do NOT fabricate expected_power
    actual_power_w = round(_get_live_power())
    return {
        "status": "weather_unavailable",
        "location": {"name": settings.location_name, "latitude": LAT, "longitude": LON},
        "data": {
            # Rough ambient estimates only — NOT used for solar calculations
            "current": {
                "temperature_2m": 35.0, "apparent_temperature": 38.0,
                "relative_humidity_2m": 45, "cloud_cover": 15,
                "wind_speed_10m": 10.0, "poa_irradiance_wm2": None,
                "shortwave_radiation": None, "precipitation": None,
            },
            "solar_radiation_wm2": None,
            # Null out all derived solar values — synthetic irradiance must not be used
            "expected_power_w":    None,
            "actual_power_w":      actual_power_w,
            "efficiency_drop_pct": None,
            "performance_ratio_used": PERFORMANCE_RATIO,
            "system_capacity_w":   CAPACITY_W,
        }
    }
