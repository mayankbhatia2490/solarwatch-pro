"""
Fleet overview API — aggregate view across all registered sites for B2B operators.
Queries InfluxDB per site_id tag using the last 2 hours of data.
"""
from fastapi import APIRouter
from datetime import datetime, timezone, timedelta
from influx import query as influx_query
from config import settings
from pathlib import Path
import json

router = APIRouter(prefix="/api/fleet", tags=["B2B Fleet"])

BUCKET = settings.influxdb_bucket
_SITES_FILE = Path("/app/data/sites.json")


def _load_sites() -> dict:
    try:
        if _SITES_FILE.exists():
            return json.loads(_SITES_FILE.read_text())
    except Exception:
        pass
    return {}


def _latest_for_site(site_id: str, field: str) -> float:
    flux = f'''
from(bucket: "{BUCKET}")
  |> range(start: -2h)
  |> filter(fn: (r) => r["site_id"] == "{site_id}")
  |> filter(fn: (r) => r["_field"] == "{field}")
  |> last()
'''
    try:
        recs = influx_query(flux)
        return float(recs[0].get_value()) if recs else 0.0
    except Exception:
        return 0.0


def _daily_energy_for_site(site_id: str) -> float:
    flux = f'''
from(bucket: "{BUCKET}")
  |> range(start: today())
  |> filter(fn: (r) => r["site_id"] == "{site_id}")
  |> filter(fn: (r) => r["_field"] == "daily_energy_kwh")
  |> last()
'''
    try:
        recs = influx_query(flux)
        return round(float(recs[0].get_value()), 2) if recs else 0.0
    except Exception:
        return 0.0


@router.get("/summary")
def fleet_summary():
    """Aggregate status across all registered sites."""
    sites = _load_sites()
    if not sites:
        return {
            "total_sites": 0,
            "healthy": 0, "warning": 0, "offline": 0,
            "total_power_kw": 0,
            "total_generation_today_kwh": 0,
            "sites": [],
            "message": "No sites registered. Use POST /api/sites to add a site.",
        }

    site_summaries = []
    total_power_w = 0.0
    total_gen_kwh = 0.0
    healthy = warning = offline = 0

    for site_id, meta in sites.items():
        power       = _latest_for_site(site_id, "power_now_w")
        health      = _latest_for_site(site_id, "health_score")
        status_code = int(_latest_for_site(site_id, "status_code"))
        temp        = _latest_for_site(site_id, "internal_radiator_temperature")
        gen_today   = _daily_energy_for_site(site_id)
        radiation   = _latest_for_site(site_id, "shortwave_radiation_wm2")

        is_daytime = radiation > 10
        if status_code == 1 and is_daytime:
            site_status = "offline"
            offline += 1
        elif health >= 80:
            site_status = "healthy"
            healthy += 1
        else:
            site_status = "warning"
            warning += 1

        total_power_w += power
        total_gen_kwh += gen_today

        site_summaries.append({
            "site_id":                site_id,
            "customer_name":          meta.get("customer_name", site_id),
            "location":               meta.get("location_name", "—"),
            "capacity_w":             meta.get("capacity_w", 0),
            "power_now_w":            round(power, 1),
            "health_score":           int(health) if health else None,
            "status":                 site_status,
            "inverter_temp_c":        round(temp, 1) if temp > 0 else None,
            "generation_today_kwh":   gen_today,
            "install_date":           meta.get("install_date"),
            "distributor":            meta.get("distributor", "—"),
        })

    site_summaries.sort(key=lambda s: s["health_score"] or 100)

    return {
        "generated_at":                datetime.now(timezone.utc).isoformat(),
        "total_sites":                  len(sites),
        "healthy":                      healthy,
        "warning":                      warning,
        "offline":                      offline,
        "total_power_kw":               round(total_power_w / 1000, 2),
        "total_generation_today_kwh":   round(total_gen_kwh, 2),
        "sites":                        site_summaries,
    }
