from fastapi import APIRouter
from influx import query
from config import settings

router = APIRouter()
BUCKET = settings.influxdb_bucket

def _latest_many(fields: list[str]) -> dict:
    fields_filter = " or ".join([f'r["_field"] == "{f}"' for f in fields])
    flux = f'''
from(bucket: "{BUCKET}")
  |> range(start: -2h)
  |> filter(fn: (r) => {fields_filter})
  |> last()
'''
    recs = query(flux)
    return {r.get_field(): r.get_value() for r in recs}

@router.get("/live")
async def electrical_live():
    """All live electrical readings — refreshed every 30s in UI"""
    # KSY 3.4kW-1Ph: single-phase (R only), 1 MPPT, 1 PV string
    fields = [
        "pv1_voltage", "pv1_current",
        "grid_r_voltage", "grid_r_current",
        "grid_frequency", "power_now_w",
        "internal_radiator_temperature", "internal_ambient_temperature",
        "expected_power_w", "status_code"
    ]
    data = _latest_many(fields)

    def f(key, default=0.0): return float(data.get(key, default))

    pv1_power = round(f("pv1_voltage") * f("pv1_current"), 1)
    ac_power  = f("power_now_w")
    efficiency = round(ac_power / pv1_power * 100, 1) if pv1_power > 0 else 0

    return {
        # Flat keys — consumed by Electrical page
        "pv1_voltage": f("pv1_voltage"), "pv1_current": f("pv1_current"), "pv1_power": pv1_power,
        "grid_voltage": f("grid_r_voltage"),
        "grid_frequency": f("grid_frequency"),
        "ac_power": ac_power,
        "inverter_temp": f("internal_radiator_temperature"),
        "efficiency": efficiency,
        # Nested structure — single string only
        "pv": {
            "string1": {"voltage": f("pv1_voltage"), "current": f("pv1_current"), "power": pv1_power},
            "total_power_w": pv1_power,
        },
        "inverter": {
            "efficiency_pct": efficiency,
            "radiator_temp_c": f("internal_radiator_temperature"),
            "ambient_temp_c": f("internal_ambient_temperature"),
            "status": "online" if int(f("status_code")) == 0 else "offline",
        },
        "ac": {
            "power_w": ac_power,
            "grid_r_voltage": f("grid_r_voltage"),
            "frequency_hz": f("grid_frequency"),
        }
    }

@router.get("/trend")
async def electrical_trend(window: str = "2h"):
    """Last N hours of electrical readings for chart"""
    valid = {"30m": "-30m", "1h": "-1h", "2h": "-2h", "6h": "-6h", "today": "today()"}
    start = valid.get(window, "-2h")

    flux = f'''
from(bucket: "{BUCKET}")
  |> range(start: {start})
  |> filter(fn: (r) => r["_field"] == "power_now_w" or
                       r["_field"] == "expected_power_w" or
                       r["_field"] == "internal_radiator_temperature")
  |> aggregateWindow(every: 5m, fn: mean, createEmpty: false)
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
'''
    recs = query(flux)
    return {"data": [
        {
            "time": r.get_time().isoformat(),
            "power_w": round(float(r.values.get("power_now_w") or 0), 1),
            "expected_w": round(float(r.values.get("expected_power_w") or 0), 1),
            "temp_c": round(float(r.values.get("internal_radiator_temperature") or 0), 1),
        }
        for r in recs
    ], "window": window}
