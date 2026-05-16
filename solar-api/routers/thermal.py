from fastapi import APIRouter, HTTPException
from typing import Dict, Any, Optional
from datetime import datetime, timezone, timedelta
from influx import query
from config import settings

router = APIRouter(prefix="/api/thermal", tags=["Thermal"])

BUCKET = settings.influxdb_bucket
_IST   = timezone(timedelta(hours=5, minutes=30))

# Thermal derating threshold for KSY inverter
# Internal radiator probe runs 20–35°C above ambient under load.
# Normal at full load: 50–75°C. Fault F8 triggers around 85–90°C.
THERMAL_WARN_C = 75.0
THERMAL_CRITICAL_C = 85.0

_15MIN = timedelta(minutes=15)


def _snap15(dt: datetime) -> str:
    """Round a UTC datetime down to the nearest 15-min slot, return IST string."""
    ist = dt.astimezone(_IST)
    snapped = ist.replace(minute=(ist.minute // 15) * 15, second=0, microsecond=0)
    return snapped.isoformat()


@router.get("/history")
def get_thermal_history(hours: int = 24) -> Dict[str, Any]:
    """
    Get Radiator and Module temperatures vs AC Power.
    module_temperature_c is null when no real sensor data is available
    (we do NOT synthesise it from radiator_temp to avoid phantom anomalies).
    module_temp_source is "measured" when a real sensor value was recorded,
    "unavailable" when the sensor field was absent or zero.
    Thermal derating anomalies are only flagged when real module_temp data exists.
    """
    try:
        # Three separate queries — aggregateWindow+pivot are broken on this instance
        range_clause = f"|> range(start: -{hours}h)"

        flux_rad = f'''
from(bucket: "{BUCKET}")
  {range_clause}
  |> filter(fn: (r) => r["_field"] == "internal_radiator_temperature")
  |> filter(fn: (r) => r["_value"] > 0)
  |> sort(columns: ["_time"])
'''
        flux_mod = f'''
from(bucket: "{BUCKET}")
  {range_clause}
  |> filter(fn: (r) => r["_field"] == "module_temperature")
  |> filter(fn: (r) => r["_value"] > 0)
  |> sort(columns: ["_time"])
'''
        flux_pwr = f'''
from(bucket: "{BUCKET}")
  {range_clause}
  |> filter(fn: (r) => r["_field"] == "power_now_w")
  |> filter(fn: (r) => r["_value"] > 0)
  |> sort(columns: ["_time"])
'''
        rad_recs = query(flux_rad)
        mod_recs = query(flux_mod)
        pwr_recs = query(flux_pwr)

        # Bucket all three fields into 15-min slots, keep last value in each slot
        rad_by_slot: dict[str, float] = {}
        for r in rad_recs:
            slot = _snap15(r.get_time())
            rad_by_slot[slot] = float(r.get_value() or 0)

        mod_by_slot: dict[str, float] = {}
        for r in mod_recs:
            slot = _snap15(r.get_time())
            mod_by_slot[slot] = float(r.get_value() or 0)

        pwr_by_slot: dict[str, float] = {}
        for r in pwr_recs:
            slot = _snap15(r.get_time())
            pwr_by_slot[slot] = float(r.get_value() or 0)

        # Union of all slots, sorted chronologically
        all_slots = sorted(set(rad_by_slot) | set(pwr_by_slot))

        timeline = []
        for slot in all_slots:
            rad_temp = round(rad_by_slot.get(slot, 0), 1)
            power    = round(pwr_by_slot.get(slot, 0), 1)

            raw_mod = mod_by_slot.get(slot)
            if raw_mod is not None and raw_mod > 0:
                mod_temp: Optional[float] = round(raw_mod, 1)
                mod_temp_source = "measured"
            else:
                mod_temp = None
                mod_temp_source = "unavailable"

            thermal_anomaly = mod_temp is not None and rad_temp > THERMAL_WARN_C

            timeline.append({
                "time":                slot,
                "radiator_temp":       rad_temp,
                "module_temperature_c": mod_temp,
                "module_temp_source":  mod_temp_source,
                "power_w":             power,
                "thermal_anomaly":     thermal_anomaly,
            })

        return {"status": "success", "data": timeline}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
