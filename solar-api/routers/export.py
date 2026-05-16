"""
CSV export — GET /api/export/csv
Downloads all solar_metrics data as a CSV file for analysis in Excel/Sheets.
"""
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
from datetime import datetime, timezone
from influx import query
from config import settings
import io

router = APIRouter(prefix="/api/export", tags=["Export"])

BUCKET = settings.influxdb_bucket

@router.get("/csv")
def export_csv(days: int = 90):
    """Export solar generation data as CSV (last N days, default 90)."""
    flux = f'''
from(bucket: "{BUCKET}")
  |> range(start: -{days}d)
  |> filter(fn: (r) =>
      r["_field"] == "power_now_w" or
      r["_field"] == "daily_energy_kwh" or
      r["_field"] == "pv1_voltage" or
      r["_field"] == "pv1_current" or
      r["_field"] == "grid_r_voltage" or
      r["_field"] == "grid_frequency" or
      r["_field"] == "internal_radiator_temperature" or
      r["_field"] == "internal_ambient_temperature")
  |> aggregateWindow(every: 15m, fn: mean, createEmpty: false)
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
  |> sort(columns: ["_time"])
'''

    records = query(flux)

    buf = io.StringIO()
    buf.write("timestamp_ist,power_w,daily_energy_kwh,pv1_voltage_v,pv1_current_a,grid_voltage_v,grid_frequency_hz,radiator_temp_c,ambient_temp_c\n")

    IST_OFFSET = 19800  # 5h30m in seconds
    for r in records:
        t = r.get_time()
        ist = datetime.fromtimestamp(t.timestamp() + IST_OFFSET, tz=timezone.utc)
        ts = ist.strftime("%Y-%m-%d %H:%M")

        def v(key): return r.values.get(key, "")
        def fmt(key):
            val = v(key)
            return f"{float(val):.2f}" if val != "" else ""

        buf.write(f"{ts},{fmt('power_now_w')},{fmt('daily_energy_kwh')},"
                  f"{fmt('pv1_voltage')},{fmt('pv1_current')},"
                  f"{fmt('grid_r_voltage')},{fmt('grid_frequency')},"
                  f"{fmt('internal_radiator_temperature')},{fmt('internal_ambient_temperature')}\n")

    buf.seek(0)
    filename = f"solarwatch_export_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"
    return StreamingResponse(
        iter([buf.read()]),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )
