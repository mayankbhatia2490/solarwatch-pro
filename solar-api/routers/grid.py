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
    R-phase voltage and frequency history.
    KSY 3.4kW-1Ph is single-phase — only R-phase data exists.
    """
    try:
        flux = f'''
        from(bucket: "{BUCKET}")
          |> range(start: -{hours}h)
          |> filter(fn: (r) => r["_field"] == "grid_r_voltage" or
                               r["_field"] == "grid_frequency")
          |> aggregateWindow(every: 10m, fn: mean, createEmpty: false)
          |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
          |> sort(columns: ["_time"])
        '''
        records = query(flux)

        timeline = []
        for r in records:
            v_r  = round(r.values.get("grid_r_voltage", 0) or 0, 1)
            freq = round(r.values.get("grid_frequency", 50) or 50, 2)
            timeline.append({
                "time":       r.get_time().isoformat(),
                "voltage_r":  v_r,
                "frequency":  freq,
            })

        return {"status": "success", "data": timeline}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
