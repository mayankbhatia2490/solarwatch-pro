from fastapi import APIRouter
from typing import Dict, Any
from datetime import datetime, timezone, timedelta, date
from config import settings
from influx import query
from cal_utils import calibration_factor

router = APIRouter(prefix="/api/performance", tags=["Performance"])

BUCKET = settings.influxdb_bucket

@router.get("")
def get_performance_data() -> Dict[str, Any]:
    """
    Returns long-term performance using real InfluxDB monthly energy data.
    YoY comparison uses actual collected data.
    Performance Ratio calculated from actual vs irradiance-based expected.
    KSY 3.4kW-1Ph specs: 98% max efficiency, PR=0.78 India standard.
    """
    now = datetime.now(timezone.utc)
    install_date = datetime.fromisoformat(settings.installation_date + "T00:00:00+00:00")

    days_old  = (now - install_date).days
    years_old = days_old / 365.25

    # Vikram Solar HyperSol warranty: 1% year 1, then 0.4%/year (30-year linear)
    # Source: Vikram Solar datasheet VSL/ENG/SC/325-V02/STD performance warranty table
    expected_deg = 1.0 + max(0, (years_old - 1) * 0.40) if years_old > 0 else 0

    # Actual degradation: compare first-month avg PR to current 30-day avg PR
    # This is a real measurement — not a formula ratio
    first_month_end = (install_date + timedelta(days=45)).date().isoformat()
    first_month_start = install_date.date().isoformat()
    flux_first = f'''
from(bucket: "{BUCKET}")
  |> range(start: {first_month_start}T00:00:00Z, stop: {first_month_end}T23:59:59Z)
  |> filter(fn: (r) => r["_field"] == "power_now_w" or r["_field"] == "expected_power_w")
  |> filter(fn: (r) => r["_value"] > 50)
  |> aggregateWindow(every: 1h, fn: mean, createEmpty: false)
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
'''
    first_recs = query(flux_first)
    first_ratios = []
    for r in first_recs:
        actual   = r.values.get("power_now_w") or 0
        expected = r.values.get("expected_power_w") or 0
        if expected > 200:
            first_ratios.append(min(actual / expected, 1.05))
    baseline_pr = (sum(first_ratios) / len(first_ratios) * 100) if len(first_ratios) >= 20 else None

    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    # Query real monthly energy totals from InfluxDB
    # Get max daily_energy_kwh per day then sum per month for last 12 months
    flux_monthly = f'''
from(bucket: "{BUCKET}")
  |> range(start: -13mo)
  |> filter(fn: (r) => r["_field"] == "daily_energy_kwh")
  |> aggregateWindow(every: 1d, fn: max, createEmpty: false)
  |> map(fn: (r) => ({{
        r with
        _month: date.month(t: r._time),
        _year: date.year(t: r._time)
  }}))
  |> group(columns: ["_month", "_year"])
  |> sum(column: "_value")
'''

    # Simpler approach: query each month individually
    yoy_data = []
    current_year = now.year
    for i in range(12):  # Jan to Dec
        month_num = i + 1

        # Current year
        if month_num <= now.month:
            start = f"{current_year}-{month_num:02d}-01T00:00:00Z"
            if month_num == 12:
                end = f"{current_year + 1}-01-01T00:00:00Z"
            else:
                end = f"{current_year}-{month_num+1:02d}-01T00:00:00Z"

            flux = f'''
from(bucket: "{BUCKET}")
  |> range(start: {start}, stop: {end})
  |> filter(fn: (r) => r["_field"] == "daily_energy_kwh")
  |> aggregateWindow(every: 1d, fn: max, createEmpty: false)
  |> sum()
'''
            recs = query(flux)
            cy_kwh = round(float(recs[0].get_value()), 1) if recs else 0
        else:
            cy_kwh = 0

        # Previous year (only useful if system existed)
        prev_year = current_year - 1
        install_year = install_date.year
        if prev_year >= install_year and month_num >= (install_date.month if prev_year == install_year else 1):
            start = f"{prev_year}-{month_num:02d}-01T00:00:00Z"
            if month_num == 12:
                end = f"{prev_year + 1}-01-01T00:00:00Z"
            else:
                end = f"{prev_year}-{month_num+1:02d}-01T00:00:00Z"

            flux = f'''
from(bucket: "{BUCKET}")
  |> range(start: {start}, stop: {end})
  |> filter(fn: (r) => r["_field"] == "daily_energy_kwh")
  |> aggregateWindow(every: 1d, fn: max, createEmpty: false)
  |> sum()
'''
            recs = query(flux)
            py_kwh = round(float(recs[0].get_value()), 1) if recs else None
        else:
            py_kwh = None

        yoy_data.append({
            "month": months[i],
            "current_year": cy_kwh,
            "prev_year": py_kwh
        })

    # Calculate real performance ratio from recent data
    # PR = Actual energy / (Irradiance * Area * Capacity)
    # Simpler: compare actual power to expected_power_w stored in InfluxDB
    flux_pr = f'''
from(bucket: "{BUCKET}")
  |> range(start: -30d)
  |> filter(fn: (r) => r["_field"] == "power_now_w" or r["_field"] == "expected_power_w")
  |> filter(fn: (r) => r["_value"] > 50)
  |> aggregateWindow(every: 1h, fn: mean, createEmpty: false)
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
'''
    pr_recs = query(flux_pr)
    pr_values = []
    for r in pr_recs:
        actual = r.values.get("power_now_w", 0) or 0
        expected = r.values.get("expected_power_w", 0) or 0
        # Apply monthly calibration to expected_power_w (written without calibration by collector)
        rec_time = r.get_time()
        month = rec_time.month
        cal = calibration_factor(month)
        expected_cal = expected * cal
        # Only include clear-sky daytime readings where expected > 200W
        # (avoids dawn/dusk noise where tiny expected values distort the ratio)
        if expected_cal > 200 and actual >= 0:
            ratio = actual / expected_cal
            # Cap individual readings at 1.05 (5% over expected is measurement noise)
            pr_values.append(min(ratio, 1.05))

    # Require at least 20 samples for a meaningful average
    # Return null when insufficient data — do NOT return hardcoded 78% baseline
    data_sufficient = len(pr_values) >= 20
    if data_sufficient:
        performance_ratio = round(sum(pr_values) / len(pr_values) * 100, 1)
        # Hard cap at 100% (physical limit)
        performance_ratio = min(performance_ratio, 100.0)
    else:
        performance_ratio = None

    # Actual degradation: difference between baseline PR and current PR (real measurement)
    if baseline_pr is not None and baseline_pr > 0:
        actual_deg = round(max(0, baseline_pr - performance_ratio), 2)
    else:
        actual_deg = None  # Not enough data yet (system too new)


    # Best days (max daily production)
    flux_best = f'''
from(bucket: "{BUCKET}")
  |> range(start: -365d)
  |> filter(fn: (r) => r["_field"] == "daily_energy_kwh")
  |> aggregateWindow(every: 1d, fn: max, createEmpty: false)
  |> sort(columns: ["_value"], desc: true)
  |> limit(n: 10)
'''
    best_recs = query(flux_best)
    best_days = [
        {"date": r.get_time().strftime("%Y-%m-%d"), "kwh": round(float(r.get_value()), 2)}
        for r in best_recs
    ]

    # Total energy fetched for lifetime stats
    flux_total = f'''
from(bucket: "{BUCKET}")
  |> range(start: 2025-04-01T00:00:00Z)
  |> filter(fn: (r) => r["_field"] == "total_energy_kwh")
  |> last()
'''
    total_recs = query(flux_total)
    total_energy_kwh = float(total_recs[0].get_value()) if total_recs else 0

    return {
        "status": "success",
        "data": {
            "system_age_days": days_old,
            "system_age_years": round(years_old, 1),
            "expected_degradation_pct": round(expected_deg, 2),
            "actual_degradation_pct": actual_deg,
            "baseline_pr": round(baseline_pr, 1) if baseline_pr else None,
            "performance_ratio": performance_ratio,
            "total_energy_kwh": round(total_energy_kwh, 1),
            "yoy_data": yoy_data,
            "best_days": best_days,
            "inverter_model": "KSY 3.4kW-1Ph",
            "inverter_max_efficiency_pct": 98.0,
            "design_pr": 78.0,
        }
    }
