from fastapi import APIRouter
from influx import query
from config import settings, solar_bill_savings
from datetime import datetime, date, timedelta, timezone
from typing import Optional
import httpx

router = APIRouter()

BUCKET = settings.influxdb_bucket
ORG = settings.influxdb_org
TARIFF = settings.electricity_tariff_inr
CAPACITY_W = settings.installed_capacity_w
CO2_KG_PER_KWH = 0.82  # India grid emission factor (CEA 2023-24)

LAT = getattr(settings, "latitude",  29.6934)
LON = getattr(settings, "longitude", 76.9994)

def _latest(field: str) -> float:
    flux = f'''
from(bucket: "{BUCKET}")
  |> range(start: -2h)
  |> filter(fn: (r) => r["_field"] == "{field}")
  |> last()
'''
    recs = query(flux)
    return float(recs[0].get_value()) if recs else 0.0

def _compute_health(live: dict) -> int:
    score = 100
    # Grid voltage check (207-253V nominal)
    v = live.get("grid_r_voltage", 230)
    if v < 207 or v > 253: score -= 20
    elif v < 215 or v > 245: score -= 10
    # Inverter RADIATOR (heatsink) temperature check
    # Datasheet: max AMBIENT operating temp = 60°C
    # Internal radiator probe runs 20-35°C above ambient under load
    # Normal at full load: 50-75°C. Fault F8 triggers around 85-90°C.
    t = live.get("internal_radiator_temperature", 40)
    if t > 85:   score -= 30  # Critical: F8 thermal fault imminent
    elif t > 75: score -= 15  # Warning: high, approaching protection limit
    # Note: 40-75°C is NORMAL for a heatsink under load on a hot Indian day
    # String balance check — KSY has 1 MPPT, 1 string
    pv1 = live.get("pv1_voltage", 0)
    if pv1 < 50 and live.get("status_code", 0) == 0:
        score -= 15  # PV1 absent despite inverter being online
    # Status check — but only penalise if it's daytime
    if live.get("status_code", 0) == 1 and not live.get("is_night", False):
        score -= 30
    return max(0, score)

async def _fetch_sunrise_sunset() -> dict:
    """Fetch today's sunrise/sunset from Open-Meteo (same API used by weather router)."""
    try:
        today = date.today().isoformat()
        url = (
            f"https://api.open-meteo.com/v1/forecast"
            f"?latitude={LAT}&longitude={LON}"
            f"&daily=sunrise,sunset"
            f"&timezone=Asia%2FKolkata"
            f"&start_date={today}&end_date={today}"
        )
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(url)
            d = r.json()
            sunrise = d.get("daily", {}).get("sunrise", [None])[0]
            sunset  = d.get("daily", {}).get("sunset",  [None])[0]
            return {"sunrise": sunrise, "sunset": sunset}
    except Exception:
        return {"sunrise": None, "sunset": None}

def _is_night(sunrise: Optional[str], sunset: Optional[str]) -> bool:
    now = datetime.now(timezone.utc).timestamp() * 1000
    if not sunrise or not sunset:
        # Fallback: Karnal 6AM–7:30PM IST
        ist_h = (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).hour
        return ist_h < 6 or ist_h >= 19
    try:
        sr = datetime.fromisoformat(sunrise).timestamp() * 1000
        ss = datetime.fromisoformat(sunset).timestamp()  * 1000
        now = datetime.now(timezone.utc).timestamp() * 1000
        return now < sr or now > ss
    except Exception:
        return False

@router.get("/summary")
async def dashboard_summary():
    """Main dashboard — all KPIs in a single call, including sunrise/sunset for night detection."""
    power = _latest("power_now_w")
    energy_today = _latest("daily_energy_kwh")
    total_energy = _latest("total_energy_kwh")
    temp = _latest("internal_radiator_temperature")
    cloud = _latest("cloud_cover_pct")
    radiation = _latest("shortwave_radiation_wm2")
    status = int(_latest("status_code"))
    pv1_v = _latest("pv1_voltage")
    pv1_a = _latest("pv1_current")
    pv2_v = _latest("pv2_voltage")
    pv2_a = _latest("pv2_current")
    grid_v = _latest("grid_r_voltage")
    grid_freq = _latest("grid_frequency")

    # Get sunrise/sunset for night detection
    sun_times = await _fetch_sunrise_sunset()
    sunrise = sun_times["sunrise"]
    sunset  = sun_times["sunset"]
    is_night = _is_night(sunrise, sunset)

    savings_today = round(energy_today * TARIFF, 1)
    co2_today = round(energy_today * CO2_KG_PER_KWH, 2)
    capacity_pct = round(power / CAPACITY_W * 100, 1) if CAPACITY_W > 0 else 0

    # Monthly savings
    flux_month = f'''
from(bucket: "{BUCKET}")
  |> range(start: {date.today().replace(day=1).isoformat()}T00:00:00Z)
  |> filter(fn: (r) => r["_field"] == "daily_energy_kwh")
  |> aggregateWindow(every: 1d, fn: max, createEmpty: false)
  |> sum()
'''
    month_recs = query(flux_month)
    energy_month = float(month_recs[0].get_value()) if month_recs else 0.0

    # Payback calculation
    install_date = datetime.fromisoformat(settings.installation_date)
    days_since_install = (datetime.now() - install_date).days
    total_savings = round(total_energy * TARIFF, 0)
    system_cost = settings.system_cost_inr
    payback_pct = round(min(total_savings / system_cost * 100, 100), 1) if system_cost > 0 else 0
    years_to_payback = round((system_cost - total_savings) / (total_savings / max(days_since_install, 1) * 365), 1) if total_savings > 0 and total_savings < system_cost else 0

    live = {
        "pv1_voltage": pv1_v, "pv1_current": pv1_a,
        "pv2_voltage": pv2_v, "pv2_current": pv2_a,
        "grid_r_voltage": grid_v, "internal_radiator_temperature": temp,
        "status_code": status, "is_night": is_night
    }
    health_score = _compute_health(live)

    # DHBVN slab-rate savings (assumes a 300 kWh/month household consumption baseline)
    # The effective savings per kWh is higher than flat rate because solar offsets expensive slabs first
    assumed_monthly_consumption = 300.0
    bill_data = solar_bill_savings(energy_month, assumed_monthly_consumption)

    return {
        "power_now_w": power,
        "capacity_pct": capacity_pct,
        "energy_today_kwh": energy_today,
        "savings_today_inr": savings_today,
        "savings_month_inr": round(energy_month * TARIFF, 1),
        "savings_month_slab_inr": bill_data["savings_inr"],
        "bill_without_solar_inr": bill_data["bill_without_solar_inr"],
        "bill_with_solar_inr": bill_data["bill_with_solar_inr"],
        "effective_tariff_inr_per_kwh": bill_data["effective_rate_inr_per_kwh"],
        "savings_total_inr": total_savings,
        "co2_today_kg": co2_today,
        "co2_total_kg": round(total_energy * CO2_KG_PER_KWH, 1),
        "trees_equivalent": round(total_energy * CO2_KG_PER_KWH / 21, 1),
        "total_energy_kwh": total_energy,
        "health_score": health_score,
        "status": "online" if status == 0 else "offline",
        "is_night": is_night,
        "sunrise": sunrise,
        "sunset": sunset,
        "inverter_temp_c": temp,
        "cloud_cover_pct": cloud,
        "solar_radiation_wm2": radiation,
        "payback_pct": payback_pct,
        "system_cost_inr": system_cost,
        "years_to_payback": years_to_payback,
        "electrical": {
            "pv1_voltage": pv1_v, "pv1_current": pv1_a,
            "pv2_voltage": pv2_v, "pv2_current": pv2_a,
            "grid_voltage": grid_v, "grid_frequency": grid_freq,
            "inverter_temp": temp
        }
    }

from fastapi import Query

@router.get("/daily-chart")
async def daily_chart(
    range: str = "today",
    from_: Optional[str] = Query(None, alias="from"),
    to_: Optional[str] = Query(None, alias="to"),
):
    """
    Generation chart data.
    range: today | yesterday | 7d | 1h | 4h | 8h | 12h | custom
    from_ / to_: ISO date strings for custom range (YYYY-MM-DD)
    """
    # Determine aggregation window based on span
    if range in ("1h",):
        start, stop, window = "-1h", "now()", "1m"
    elif range == "4h":
        start, stop, window = "-4h", "now()", "5m"
    elif range == "8h":
        start, stop, window = "-8h", "now()", "5m"
    elif range == "12h":
        start, stop, window = "-12h", "now()", "10m"
    elif range == "today":
        start = f"{date.today().isoformat()}T00:00:00Z"
        stop, window = "now()", "5m"
    elif range == "yesterday":
        d = date.today() - timedelta(days=1)
        start = f"{d.isoformat()}T00:00:00Z"
        stop   = f"{date.today().isoformat()}T00:00:00Z"
        window = "5m"
    elif range == "7d":
        start, stop, window = "-7d", "now()", "30m"
    elif range == "custom" and from_ and to_:
        start  = f"{from_}T00:00:00Z"
        stop   = f"{to_}T23:59:59Z"
        # Adaptive window: roughly 300 points
        days = max((datetime.fromisoformat(to_) - datetime.fromisoformat(from_)).days + 1, 1)
        mins = days * 24 * 60
        bucket_mins = max(mins // 300, 5)
        window = f"{bucket_mins}m"
    else:
        start, stop, window = "-1d", "now()", "5m"

    stop_clause = f"|> range(start: {start}, stop: {stop})" if stop != "now()" else f"|> range(start: {start})"

    flux = f'''
from(bucket: "{BUCKET}")
  {stop_clause}
  |> filter(fn: (r) => r["_field"] == "power_now_w" or r["_field"] == "expected_power_w")
  |> aggregateWindow(every: {window}, fn: mean, createEmpty: false)
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
'''
    recs = query(flux)
    chart_data = []
    for r in recs:
        vals = r.values
        chart_data.append({
            "time": r.get_time().isoformat(),
            "power_w":    round(float(vals.get("power_now_w")    or 0), 1),
            "expected_w": round(float(vals.get("expected_power_w") or 0), 1),
        })
    return {"data": chart_data, "range": range}

@router.get("/health-scorecard")
async def health_scorecard():
    """Per-parameter health status for the table card"""
    def status(val, low, high, unit=""):
        if val == 0:
            return {"value": "—", "status": "unknown"}
        ok = low <= val <= high
        warn = (low * 0.95) <= val <= (high * 1.05)
        s = "normal" if ok else ("warning" if warn else "critical")
        return {"value": f"{val:.1f}{unit}", "status": s}

    pv1_v = _latest("pv1_voltage")
    pv1_a = _latest("pv1_current")
    pv2_v = _latest("pv2_voltage")
    pv2_a = _latest("pv2_current")
    grid_v = _latest("grid_r_voltage")
    grid_freq = _latest("grid_frequency")
    temp = _latest("internal_radiator_temperature")
    power = _latest("power_now_w")

    pv1_power = round(pv1_v * pv1_a, 0)
    pv2_power = round(pv2_v * pv2_a, 0)

    return {"rows": [
        {"parameter": "Grid Voltage", **status(grid_v, 207, 253, "V")},
        {"parameter": "Grid Frequency", **status(grid_freq, 49.5, 50.5, "Hz")},
        {"parameter": "PV String 1",
         "value": f"{pv1_v:.0f}V / {pv1_a:.1f}A ({pv1_power:.0f}W)",
         "status": "normal" if pv1_v > 70 else ("warning" if pv1_v > 0 else "unknown")},
        # KSY 5G-PRO+ = 1 MPPT, 1 String — PV2 port is not used
        {"parameter": "PV String 2",
         "value": "Not connected (single-string system)" if pv2_v < 5 else f"{pv2_v:.0f}V / {pv2_a:.1f}A ({pv2_power:.0f}W)",
         "status": "normal" if pv2_v < 5 else ("normal" if pv2_v > 70 else "warning")},
        # Radiator temp: normal 40-75°C under load, warn >75°C, critical >85°C
        {"parameter": "Inverter Temp",
         "value": f"{temp:.1f}°C",
         "status": "critical" if temp > 85 else ("warning" if temp > 75 else "normal")},
        {"parameter": "AC Output", "value": f"{power:.0f}W", "status": "normal" if power >= 0 else "critical"},
    ]}
