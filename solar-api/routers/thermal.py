from fastapi import APIRouter, HTTPException
from typing import Dict, Any, Optional
from datetime import datetime, timezone, timedelta
from influx import query
from config import settings

router = APIRouter(prefix="/api/thermal", tags=["Thermal"])

BUCKET = settings.influxdb_bucket

# Thermal derating threshold for KSY inverter
# Internal radiator probe runs 20–35°C above ambient under load.
# Normal at full load: 50–75°C. Fault F8 triggers around 85–90°C.
THERMAL_WARN_C = 75.0
THERMAL_CRITICAL_C = 85.0


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
        flux = f'''
        from(bucket: "{BUCKET}")
          |> range(start: -{hours}h)
          |> filter(fn: (r) => r["_field"] == "internal_radiator_temperature" or
                               r["_field"] == "module_temperature" or
                               r["_field"] == "power_now_w")
          |> aggregateWindow(every: 15m, fn: mean, createEmpty: false)
          |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
          |> sort(columns: ["_time"])
        '''
        records = query(flux)

        timeline = []
        for r in records:
            rad_temp = round(r.values.get("internal_radiator_temperature", 0) or 0, 1)
            power = round(r.values.get("power_now_w", 0) or 0, 1)

            # Use real module temperature only — null when unavailable.
            # Previously: mod_temp = rad_temp + 2.5 (synthetic fallback) — REMOVED.
            # Synthetic values caused phantom thermal derating anomalies.
            raw_mod_temp = r.values.get("module_temperature")
            if raw_mod_temp is not None and float(raw_mod_temp) > 0:
                mod_temp: Optional[float] = round(float(raw_mod_temp), 1)
                mod_temp_source = "measured"
            else:
                mod_temp = None
                mod_temp_source = "unavailable"

            # Thermal anomaly detection: only flag when real module_temp data is present.
            # Do NOT compute derating anomalies from synthetic/null values.
            thermal_anomaly = False
            if mod_temp is not None and rad_temp > THERMAL_WARN_C:
                thermal_anomaly = True

            timeline.append({
                "time": r.get_time().isoformat(),
                "radiator_temp": rad_temp,
                "module_temperature_c": mod_temp,
                "module_temp_source": mod_temp_source,
                "power_w": power,
                "thermal_anomaly": thermal_anomaly,
            })

        return {"status": "success", "data": timeline}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
