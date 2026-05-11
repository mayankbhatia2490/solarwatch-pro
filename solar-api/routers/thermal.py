from fastapi import APIRouter, HTTPException
from typing import Dict, Any
from datetime import datetime, timezone, timedelta
from influx import query
from config import settings

router = APIRouter(prefix="/api/thermal", tags=["Thermal"])

BUCKET = settings.influxdb_bucket

@router.get("/history")
def get_thermal_history(hours: int = 24) -> Dict[str, Any]:
    """
    Get Radiator and Module temperatures vs AC Power.
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
            # If module temperature isn't available, simulate slightly higher than radiator for UI testing
            mod_temp = round(r.values.get("module_temperature", rad_temp + 2.5) or (rad_temp + 2.5), 1)
            power = round(r.values.get("power_now_w", 0) or 0, 1)
            
            timeline.append({
                "time": r.get_time().isoformat(),
                "radiator_temp": rad_temp,
                "module_temp": mod_temp,
                "power_w": power
            })

        return {"status": "success", "data": timeline}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
