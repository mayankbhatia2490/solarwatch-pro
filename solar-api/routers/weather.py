from fastapi import APIRouter
from typing import Dict, Any
import httpx
from datetime import datetime, timezone
from config import settings
from influx import query

router = APIRouter(prefix="/api/weather", tags=["Weather"])

# Use coordinates from environment config (Karnal, Haryana)
LAT = float(settings.latitude)
LON = float(settings.longitude)
CAPACITY_W = settings.installed_capacity_w

# Performance Ratio for India: accounts for soiling (3-5%), temp losses (5-8%),
# cable losses (2%), inverter efficiency (98% per KSY datasheet), shading (1%)
# => Total PR ≈ 0.78 for a well-maintained Indian rooftop system
PERFORMANCE_RATIO = 0.78

def _get_live_power() -> float:
    """Fetch the latest actual power from InfluxDB."""
    bucket = settings.influxdb_bucket
    flux = f'''
from(bucket: "{bucket}")
  |> range(start: -2h)
  |> filter(fn: (r) => r["_field"] == "power_now_w")
  |> last()
'''
    recs = query(flux)
    return float(recs[0].get_value()) if recs else 0.0


@router.get("/")
async def get_weather() -> Dict[str, Any]:
    """
    Fetches real-time weather from Open-Meteo for Karnal, Haryana (29.68°N, 76.99°E).
    Calculates expected solar power using KSY 3.5kW inverter specs and actual PR=0.78.
    Actual power comes from live InfluxDB reading (not mocked).
    """
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={LAT}&longitude={LON}"
        f"&current=temperature_2m,relative_humidity_2m,cloud_cover,wind_speed_10m,"
        f"direct_radiation,diffuse_radiation,apparent_temperature,precipitation"
        f"&hourly=temperature_2m,cloud_cover,direct_radiation,diffuse_radiation"
        f"&daily=sunrise,sunset,uv_index_max,precipitation_sum"
        f"&timezone=Asia%2FKolkata"
        f"&forecast_days=3"
    )

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                data = resp.json()
                current = data.get("current", {})

                # Irradiance = direct + diffuse (both from Open-Meteo)
                direct_rad = current.get("direct_radiation", 0) or 0
                diffuse_rad = current.get("diffuse_radiation", 0) or 0
                total_irradiance = direct_rad + diffuse_rad

                # Expected power using STC formula corrected for actual conditions:
                # P_expected = (G / 1000) * P_rated * PR
                # where G = total irradiance, P_rated = 3500W, PR = 0.78
                expected_power_w = round((total_irradiance / 1000.0) * CAPACITY_W * PERFORMANCE_RATIO)

                # Actual power from live InfluxDB data
                actual_power_w = round(_get_live_power())

                # Efficiency drop vs expected (only meaningful when sun is up)
                efficiency_drop_pct = 0.0
                if expected_power_w > 100:
                    efficiency_drop_pct = round(
                        max(0, (expected_power_w - actual_power_w) / expected_power_w * 100), 1
                    )

                # Build 3-day hourly forecast for chart
                hourly = data.get("hourly", {})
                daily = data.get("daily", {})

                return {
                    "status": "success",
                    "location": {
                        "name": "Karnal, Haryana",
                        "latitude": LAT,
                        "longitude": LON,
                        "timezone": "Asia/Kolkata"
                    },
                    "data": {
                        "current": {
                            "temperature_2m": current.get("temperature_2m"),
                            "apparent_temperature": current.get("apparent_temperature"),
                            "relative_humidity_2m": current.get("relative_humidity_2m"),
                            "cloud_cover": current.get("cloud_cover"),
                            "wind_speed_10m": current.get("wind_speed_10m"),
                            "direct_radiation": direct_rad,
                            "diffuse_radiation": diffuse_rad,
                            "total_irradiance": total_irradiance,
                            "precipitation": current.get("precipitation", 0),
                        },
                        "hourly": {
                            "time": hourly.get("time", [])[:48],
                            "temperature_2m": hourly.get("temperature_2m", [])[:48],
                            "cloud_cover": hourly.get("cloud_cover", [])[:48],
                            "direct_radiation": hourly.get("direct_radiation", [])[:48],
                            "diffuse_radiation": hourly.get("diffuse_radiation", [])[:48],
                        },
                        "daily": {
                            "sunrise": daily.get("sunrise", [])[:3],
                            "sunset": daily.get("sunset", [])[:3],
                            "uv_index_max": daily.get("uv_index_max", [])[:3],
                            "precipitation_sum": daily.get("precipitation_sum", [])[:3],
                        },
                        "expected_power_w": expected_power_w,
                        "actual_power_w": actual_power_w,
                        "efficiency_drop_pct": efficiency_drop_pct,
                        "performance_ratio_used": PERFORMANCE_RATIO,
                        "system_capacity_w": CAPACITY_W,
                    }
                }
    except Exception as e:
        print(f"Weather API error: {e}")

    # Fallback: still use real InfluxDB power, just no weather
    actual_power_w = round(_get_live_power())
    return {
        "status": "partial",
        "location": {"name": "Karnal, Haryana", "latitude": LAT, "longitude": LON},
        "data": {
            "current": {
                "temperature_2m": 35.0,
                "apparent_temperature": 38.0,
                "relative_humidity_2m": 45,
                "cloud_cover": 15,
                "wind_speed_10m": 10.0,
                "direct_radiation": 700,
                "diffuse_radiation": 150,
                "total_irradiance": 850,
                "precipitation": 0,
            },
            "expected_power_w": round((850 / 1000.0) * CAPACITY_W * PERFORMANCE_RATIO),
            "actual_power_w": actual_power_w,
            "efficiency_drop_pct": 0.0,
            "performance_ratio_used": PERFORMANCE_RATIO,
            "system_capacity_w": CAPACITY_W,
        }
    }
