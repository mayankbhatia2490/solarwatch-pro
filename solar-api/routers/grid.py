from fastapi import APIRouter, HTTPException
from typing import Dict, Any
from datetime import datetime, timezone, timedelta
from influx import query
from config import settings

router = APIRouter(prefix="/api/grid", tags=["Grid"])

BUCKET = settings.influxdb_bucket

@router.get("/history")
def get_grid_history(hours: int = 24) -> Dict[str, Any]:
    """
    Get R, S, T phase voltages and frequency over the specified time range.
    """
    try:
        flux = f'''
        from(bucket: "{BUCKET}")
          |> range(start: -{hours}h)
          |> filter(fn: (r) => r["_field"] == "grid_r_voltage" or 
                               r["_field"] == "grid_s_voltage" or 
                               r["_field"] == "grid_t_voltage" or 
                               r["_field"] == "grid_frequency")
          |> aggregateWindow(every: 10m, fn: mean, createEmpty: false)
          |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
          |> sort(columns: ["_time"])
        '''
        records = query(flux)
        
        timeline = []
        for r in records:
            # Fallbacks if phase S/T are missing from old data
            v_r = round(r.values.get("grid_r_voltage", 0) or 0, 1)
            v_s = round(r.values.get("grid_s_voltage", v_r) or v_r, 1) 
            v_t = round(r.values.get("grid_t_voltage", v_r) or v_r, 1)
            freq = round(r.values.get("grid_frequency", 50) or 50, 2)
            
            # Calculate phase imbalance (max deviation from average)
            avg_v = (v_r + v_s + v_t) / 3
            imbalance = 0
            if avg_v > 0:
                max_dev = max(abs(v_r - avg_v), abs(v_s - avg_v), abs(v_t - avg_v))
                imbalance = round((max_dev / avg_v) * 100, 1)

            timeline.append({
                "time": r.get_time().isoformat(),
                "voltage_r": v_r,
                "voltage_s": v_s,
                "voltage_t": v_t,
                "frequency": freq,
                "imbalance_pct": imbalance
            })

        return {"status": "success", "data": timeline}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
