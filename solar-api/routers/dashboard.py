from fastapi import APIRouter, Query
from influx import query
from config import settings, solar_bill_savings
from datetime import datetime, date, timedelta, timezone
from typing import Optional
import httpx
import asyncio
from cal_utils import calibration_factor, actual_kwh as _correct
import inverter as inv

router = APIRouter()

BUCKET     = settings.influxdb_bucket
ORG        = settings.influxdb_org
TARIFF     = settings.electricity_tariff_inr
CAPACITY_W = settings.installed_capacity_w
CO2_KG_PER_KWH = 0.82

LAT = float(settings.latitude)
LON = float(settings.longitude)

PANEL_TILT         = 5
PANEL_AZIMUTH      = 0
PR                 = 0.83
BIFACIAL_REAR_GAIN = 0.09
TEMP_COEFF         = -0.0030
NOCT               = 45.0


def _expected_w(poa: float, temp_c: float, month: int) -> float:
    T_cell = temp_c + (NOCT - 20.0) * (poa / 800.0)
    corr   = 1 + TEMP_COEFF * (T_cell - 25.0)
    cal    = calibration_factor(month)
    return max(0.0, (poa / 1000.0) * CAPACITY_W * (1 + BIFACIAL_REAR_GAIN) * PR * corr * cal)


async def _om_expected_map(past_days: int) -> dict[str, float]:
    """
    Fetch Open-Meteo historical hourly GTI + temperature.
    Returns {iso_hour_str: expected_w} e.g. {"2026-05-10T08:00": 1450.3}
    Timestamps are in IST (timezone=Asia/Kolkata).
    """
    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={LAT}&longitude={LON}"
        f"&hourly=temperature_2m,global_tilted_irradiance"
        f"&tilt={PANEL_TILT}&azimuth={PANEL_AZIMUTH}"
        f"&timezone=Asia%2FKolkata"
        f"&past_days={min(past_days, 92)}&forecast_days=1"
    )
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            hourly = resp.json().get("hourly", {})
        result = {}
        times = hourly.get("time", [])
        poas  = hourly.get("global_tilted_irradiance", [])
        temps = hourly.get("temperature_2m", [])
        for i, t in enumerate(times):
            poa    = float(poas[i]  or 0) if i < len(poas)  else 0
            temp_c = float(temps[i] or 30) if i < len(temps) else 30
            if poa < 10:
                continue
            month = int(t[5:7]) if len(t) >= 7 else date.today().month
            result[t] = round(_expected_w(poa, temp_c, month), 1)
        return result
    except Exception as e:
        print(f"OM expected map error: {e}")
        return {}

def _latest(field: str, hours: int = 2) -> float:
    flux = f'''
from(bucket: "{BUCKET}")
  |> range(start: -{hours}h)
  |> filter(fn: (r) => r["_field"] == "{field}")
  |> last()
'''
    recs = query(flux)
    return float(recs[0].get_value()) if recs else 0.0

def _latest_persistent(field: str) -> float:
    """For cumulative counters (total_energy_kwh) — survives overnight gaps by looking back 48h."""
    for hours in [2, 48]:
        val = _latest(field, hours=hours)
        if val > 0:
            return val
    return 0.0

def _compute_health(live: dict) -> int:
    # At night the inverter is off — all live readings are stale zeroes.
    # Skip electrical checks; return 95 (resting, last known state OK).
    if live.get("is_night", False):
        return 95

    score = 100
    # Grid voltage — single-phase (KSY 3.4KW-1Ph), R phase only
    v = live.get("grid_r_voltage", 230)
    if v < 207 or v > 253: score -= 20
    elif v < 215 or v > 245: score -= 10
    # Heatsink temperature: normal 40-75°C under load; warn >75°C; F8 fault risk >85°C
    t = live.get("internal_radiator_temperature", 40)
    if t > 85:   score -= 30
    elif t > 75: score -= 15
    # Performance ratio during daylight
    power    = live.get("power_now_w", 0)
    expected = live.get("expected_power_w", 0)
    if expected > 200:
        pr = power / expected
        if pr < 0.60:   score -= 15
        elif pr < 0.80: score -= 5
    # PV1 absent while online during daylight
    pv1 = live.get("pv1_voltage", 0)
    if pv1 < 50 and live.get("status_code", 0) == 0:
        score -= 15
    # Inverter offline during daylight
    if live.get("status_code", 0) == 1:
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
    energy_today = _correct(_latest("daily_energy_kwh"))
    total_energy = _correct(_latest_persistent("total_energy_kwh"))
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

    # Monthly energy — aggregateWindow/pivot don't work on this InfluxDB instance.
    # Query all daily_energy_kwh since month start, keep max per IST day, sum in Python.
    _IST_OFF = timezone(timedelta(hours=5, minutes=30))
    flux_month = f'''
from(bucket: "{BUCKET}")
  |> range(start: {date.today().replace(day=1).isoformat()}T00:00:00Z)
  |> filter(fn: (r) => r["_field"] == "daily_energy_kwh")
  |> filter(fn: (r) => r["_value"] > 0)
  |> sort(columns: ["_time"])
'''
    month_recs = query(flux_month)
    _day_max: dict[str, float] = {}
    for rec in month_recs:
        day_key = rec.get_time().astimezone(_IST_OFF).strftime("%Y-%m-%d")
        val = float(rec.get_value() or 0)
        if val > _day_max.get(day_key, 0.0):
            _day_max[day_key] = val
    energy_month = _correct(sum(_day_max.values()))

    # Payback calculation
    install_date = datetime.fromisoformat(settings.installation_date)
    days_since_install = (datetime.now() - install_date).days
    total_savings = round(total_energy * TARIFF, 0)
    system_cost = settings.system_cost_inr
    payback_pct = round(min(total_savings / system_cost * 100, 100), 1) if system_cost > 0 else 0
    years_to_payback = round((system_cost - total_savings) / (total_savings / max(days_since_install, 1) * 365), 1) if total_savings > 0 and total_savings < system_cost else 0

    expected_power = _latest("expected_power_w")
    live = {
        "pv1_voltage": pv1_v, "pv1_current": pv1_a,
        "pv2_voltage": pv2_v, "pv2_current": pv2_a,
        "grid_r_voltage": grid_v, "internal_radiator_temperature": temp,
        "status_code": status, "is_night": is_night,
        "power_now_w": power, "expected_power_w": expected_power,
    }
    health_score = _compute_health(live)

    # UHBVN slab-rate savings — use real average monthly consumption from stored bills
    # Falls back to 300 kWh/month if no electricity_bill measurement in InfluxDB
    flux_bills = f'''
from(bucket: "{BUCKET}")
  |> range(start: -365d)
  |> filter(fn: (r) => r["_measurement"] == "electricity_bill" and r["_field"] == "units_consumed_kwh")
  |> mean()
'''
    bill_recs = query(flux_bills)
    assumed_monthly_consumption = float(bill_recs[0].get_value()) if bill_recs else 300.0
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
        # 22 kg CO2/tree/year — ICFRE estimate for Indian deciduous species
        "trees_equivalent": round(total_energy * CO2_KG_PER_KWH / 22, 1),
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

@router.get("/daily-chart")
async def daily_chart(
    range: str = "today",
    from_: Optional[str] = Query(None, alias="from"),
    to_: Optional[str] = Query(None, alias="to"),
):
    """
    Generation chart data.
    range: today | yesterday | 7d | 1h | 4h | 8h | 12h | custom

    For intra-day ranges (≤12h) both power_now_w and expected_power_w come from
    InfluxDB — the collector is almost certainly running live.

    For multi-day ranges (7d, yesterday, custom ≥2d) expected_w is computed from
    Open-Meteo historical irradiance so the expected curve is always complete and
    bell-shaped regardless of whether the collector had any downtime gaps.
    """
    multi_day = False   # whether to use Open-Meteo for expected

    if range == "1h":
        start, stop, window, past_days = "-1h",  "now()", "1m",  0
    elif range == "4h":
        start, stop, window, past_days = "-4h",  "now()", "5m",  0
    elif range == "8h":
        start, stop, window, past_days = "-8h",  "now()", "5m",  0
    elif range == "12h":
        start, stop, window, past_days = "-12h", "now()", "10m", 0
    elif range == "today":
        start = f"{date.today().isoformat()}T00:00:00Z"
        stop, window, past_days = "now()", "5m", 0
    elif range == "yesterday":
        d = date.today() - timedelta(days=1)
        start = f"{d.isoformat()}T00:00:00Z"
        stop   = f"{date.today().isoformat()}T00:00:00Z"
        window, past_days, multi_day = "5m", 2, True
    elif range == "7d":
        start, stop, window, past_days, multi_day = "-7d", "now()", "30m", 7, True
    elif range == "custom" and from_ and to_:
        start = f"{from_}T00:00:00Z"
        stop  = f"{to_}T23:59:59Z"
        span_days = max((datetime.fromisoformat(to_) - datetime.fromisoformat(from_)).days + 1, 1)
        bucket_mins = max(span_days * 24 * 60 // 300, 5)
        window    = f"{bucket_mins}m"
        past_days = span_days + 1
        multi_day = span_days >= 2
    else:
        start, stop, window, past_days = "-1d", "now()", "5m", 0

    stop_clause = f"|> range(start: {start}, stop: {stop})" if stop != "now()" else f"|> range(start: {start})"

    # ── Build Flux queries ────────────────────────────────────────────────────
    # aggregateWindow() and pivot() both return empty on this InfluxDB version.
    # Filter out zero values — inverter writes 0 at night; chart only needs
    # real generation data. sort() is the only Flux transform that works here.
    flux_power = f'''
from(bucket: "{BUCKET}")
  {stop_clause}
  |> filter(fn: (r) => r["_field"] == "power_now_w")
  |> filter(fn: (r) => r["_value"] > 0)
  |> sort(columns: ["_time"])
'''
    flux_expected = f'''
from(bucket: "{BUCKET}")
  {stop_clause}
  |> filter(fn: (r) => r["_field"] == "expected_power_w")
  |> filter(fn: (r) => r["_value"] > 0)
  |> sort(columns: ["_time"])
'''

    loop = asyncio.get_running_loop()
    if multi_day:
        # Expected comes from Open-Meteo — only need power from InfluxDB.
        power_recs, om_map = await asyncio.gather(
            loop.run_in_executor(None, lambda: query(flux_power)),
            _om_expected_map(past_days),
        )
        exp_recs = []
    else:
        power_recs, exp_recs = await asyncio.gather(
            loop.run_in_executor(None, lambda: query(flux_power)),
            loop.run_in_executor(None, lambda: query(flux_expected)),
        )
        om_map = {}

    # ── Build chart data ──────────────────────────────────────────────────────
    _IST = timezone(timedelta(hours=5, minutes=30))

    # Build expected lookup by timestamp (for short-range InfluxDB path)
    exp_by_ts: dict = {r.get_time(): round(float(r.get_value() or 0), 1) for r in exp_recs}

    chart_data = []
    for r in power_recs:
        ts      = r.get_time()
        power_w = round(float(r.get_value() or 0), 1)

        if om_map:
            ist_dt     = ts.astimezone(_IST)
            hour_key   = ist_dt.strftime("%Y-%m-%dT%H:00")
            expected_w = om_map.get(hour_key, 0.0)
        else:
            expected_w = exp_by_ts.get(ts, 0.0)

        chart_data.append({
            "time":       ts.isoformat(),
            "power_w":    power_w,
            "expected_w": round(expected_w, 1),
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
        # KSY 3.4kW-1Ph = 1 MPPT, 1 String — no second string on this inverter
        # Radiator temp: normal 40-75°C under load, warn >75°C, critical >85°C
        {"parameter": "Inverter Temp",
         "value": f"{temp:.1f}°C",
         "status": "critical" if temp > 85 else ("warning" if temp > 75 else "normal")},
        {"parameter": "AC Output", "value": f"{power:.0f}W", "status": "normal" if power >= 0 else "critical"},
    ]}


@router.get("/inverter")
async def inverter_diagnostics():
    """
    KSolar 5G-PRO+ specific diagnostics.
    Uses inverter internal ambient sensor (not Open-Meteo) for thermal assessment.
    """
    power    = _latest("power_now_w")
    pv1_v    = _latest("pv1_voltage")
    pv1_a    = _latest("pv1_current")
    # internal_ambient_temperature = inverter's own internal sensor (near the inverter, not Karnal weather)
    radiator = _latest("internal_radiator_temperature")
    ambient  = _latest("internal_ambient_temperature")   # inverter case ambient, not city weather
    poa      = _latest("poa_irradiance_wm2")

    # Fault code — string field, needs separate query
    flux_fault = f'''
from(bucket: "{BUCKET}")
  |> range(start: -24h)
  |> filter(fn: (r) => r["_field"] == "fault_code_str")
  |> last()
'''
    fault_recs  = query(flux_fault)
    fault_code  = str(fault_recs[0].get_value()) if fault_recs else None

    # Efficiency trend — last 30 readings
    flux_eff = f'''
from(bucket: "{BUCKET}")
  |> range(start: -3h)
  |> filter(fn: (r) => r["_field"] == "dc_ac_efficiency_pct")
  |> filter(fn: (r) => r["_value"] > 0)
  |> sort(columns: ["_time"])
'''
    eff_recs = query(flux_eff)
    eff_vals = [round(float(r.get_value()), 1) for r in eff_recs if r.get_value()]
    avg_eff  = round(sum(eff_vals) / len(eff_vals), 1) if eff_vals else None
    live_eff = eff_vals[-1] if eff_vals else inv.dc_ac_efficiency(power, pv1_v, pv1_a)

    from datetime import datetime
    hour = datetime.now(timezone(timedelta(hours=5, minutes=30))).hour

    fault_decoded  = inv.decode_fault(fault_code)
    eff_ctx        = inv.efficiency_context(live_eff, power)
    thermal        = inv.thermal_context(radiator, ambient if ambient > 0 else radiator - 15)
    voltage_hdr    = inv.pv_voltage_headroom(pv1_v)
    shading        = inv.shading_signal(pv1_v, poa, hour)

    return {
        "model":            "KSY-3.4KW-1Ph",
        "rated_ac_w":       inv.RATED_AC_W,
        "max_dc_voltage_v": inv.MAX_DC_VOLTAGE_V,
        "num_mppt":         inv.NUM_MPPT,
        "fault_code":       fault_code,
        "fault_decoded":    fault_decoded,
        "efficiency": {
            "live_pct":    live_eff,
            "avg_3h_pct":  avg_eff,
            "spec_peak":   inv.MAX_EFFICIENCY * 100,
            "context":     eff_ctx,
        },
        "thermal":          thermal,
        "voltage_headroom": voltage_hdr,
        "shading_signal":   shading,
        "raw": {
            "power_ac_w":       power,
            "pv1_voltage_v":    pv1_v,
            "pv1_current_a":    pv1_a,
            "pv1_dc_w":         round(pv1_v * pv1_a, 1),
            "radiator_temp_c":  radiator,
            "internal_ambient_c": ambient,
            "poa_wm2":          poa,
        },
    }
