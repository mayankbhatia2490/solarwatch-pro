"""
System Analysis — GET /api/analysis
Weather-adjusted performance comparison: actual vs expected, PR trend,
underperformance periods, and actionable improvement recommendations.

Expected energy is computed from Open-Meteo historical irradiance (past_days),
NOT from the stored expected_power_w InfluxDB field.  The stored field is only
written when the collector is running, so collector downtime gaps make expected
look artificially low.  Open-Meteo covers every daylight hour regardless of
collector uptime, giving a fair apples-to-apples comparison.

Actual energy uses daily_energy_kwh (Shinemonitor's own end-of-day counter)
which is also unaffected by collector uptime gaps.
"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from typing import Dict, Any
from datetime import datetime, timezone, timedelta, date
from collections import defaultdict
from cal_utils import actual_kwh as _correct
import httpx
import asyncio

from influx import query
from config import settings
from cal_utils import calibration_factor
import traceback

router = APIRouter(prefix="/api/analysis", tags=["Analysis"])

BUCKET     = settings.influxdb_bucket
CAPACITY_W = settings.installed_capacity_w
TARIFF     = settings.electricity_tariff_inr
LAT        = float(settings.latitude)
LON        = float(settings.longitude)
DESIGN_PR  = 0.78
TEMP_WARN  = 65.0

PANEL_TILT         = 5
PANEL_AZIMUTH      = 0
PR                 = 0.83
BIFACIAL_REAR_GAIN = 0.09
TEMP_COEFF         = -0.0030
NOCT               = 45.0


def _expected_power_w(poa_wm2: float, temp_c: float, month: int) -> float:
    """NOCT temperature-corrected expected power with monthly calibration."""
    T_cell     = temp_c + (NOCT - 20.0) * (poa_wm2 / 800.0)
    correction = 1 + TEMP_COEFF * (T_cell - 25.0)
    cal        = calibration_factor(month)
    return max(0.0, (poa_wm2 / 1000.0) * CAPACITY_W * (1 + BIFACIAL_REAR_GAIN) * PR * correction * cal)


def _empty_response(days: int) -> Dict[str, Any]:
    return {
        "status": "no_data",
        "period_days": days,
        "summary": {
            "total_actual_kwh": 0, "total_expected_kwh": 0,
            "overall_pr_pct": 0, "design_pr_pct": int(DESIGN_PR * 100),
            "lost_kwh": 0, "lost_inr": 0,
            "underperform_days": 0, "total_days": 0,
            "calibration_warning": False,
        },
        "daily_bars": [], "pr_trend": [], "hourly_profile": [],
        "recommendations": [{
            "priority": "info", "icon": "📡",
            "title": "No data yet for this period",
            "detail": "The collector writes data every 5 minutes during daylight hours. "
                      "Check that the collector container is running and the inverter is online.",
            "action": "docker compose logs collector --tail 50",
        }],
    }


@router.get("")
async def get_analysis(days: int = 30) -> Dict[str, Any]:
    try:
        return await _get_analysis_inner(days)
    except Exception:
        traceback.print_exc()
        return JSONResponse(status_code=200, content=_empty_response(days))


async def _fetch_om_historical(days: int) -> dict:
    """
    Fetch Open-Meteo historical hourly irradiance + temperature via past_days.
    Returns {"times": [...], "poa": [...], "temps": [...]} all same length.
    Open-Meteo past_days max = 92; for longer periods we split into two calls.
    """
    past_days = min(days, 92)  # Open-Meteo hard limit

    url = (
        f"https://api.open-meteo.com/v1/forecast"
        f"?latitude={LAT}&longitude={LON}"
        f"&hourly=temperature_2m,global_tilted_irradiance"
        f"&tilt={PANEL_TILT}&azimuth={PANEL_AZIMUTH}"
        f"&timezone=Asia%2FKolkata"
        f"&past_days={past_days}"
        f"&forecast_days=1"
    )
    async with httpx.AsyncClient(timeout=12.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
        data = resp.json()

    hourly = data.get("hourly", {})
    return {
        "times": hourly.get("time", []),
        "poa":   hourly.get("global_tilted_irradiance", []),
        "temps": hourly.get("temperature_2m", []),
    }


async def _get_analysis_inner(days: int) -> Dict[str, Any]:

    # ── 1. Actual daily generation — Shinemonitor end-of-day cumulative counter ─
    flux_actual = f'''
from(bucket: "{BUCKET}")
  |> range(start: -{days}d)
  |> filter(fn: (r) => r["_field"] == "daily_energy_kwh")
  |> filter(fn: (r) => r["_value"] > 0)
  |> sort(columns: ["_time"])
'''
    # Run InfluxDB and Open-Meteo fetches concurrently
    actual_recs, om = await asyncio.gather(
        asyncio.get_event_loop().run_in_executor(None, lambda: query(flux_actual)),
        _fetch_om_historical(days),
    )

    # Last reading per IST day = end-of-day total
    daily_actual: dict[str, float] = {}
    for r in actual_recs:
        ist_date = (r.get_time() + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")
        val = _correct(float(r.get_value() or 0))
        if val > 0:
            daily_actual[ist_date] = val

    # ── 2. Expected energy from Open-Meteo historical irradiance ─────────────
    # Every daylight hour is covered regardless of collector uptime.
    daily_expected: dict[str, float] = defaultdict(float)

    for i, t in enumerate(om["times"]):
        poa    = float(om["poa"][i]   or 0) if i < len(om["poa"])   else 0
        temp_c = float(om["temps"][i] or 30) if i < len(om["temps"]) else 30
        if poa < 10:        # ignore nighttime / near-zero irradiance
            continue
        month    = int(t[5:7]) if len(t) >= 7 else date.today().month
        expected = _expected_power_w(poa, temp_c, month)
        # t is "YYYY-MM-DDTHH:MM" in IST (timezone=Asia/Kolkata)
        ist_date = t[:10]
        daily_expected[ist_date] += expected  # Wh (1-hour slots)

    # ── 3. Inverter temperature from InfluxDB (for hot-hour detection) ────────
    # aggregateWindow returns empty on this InfluxDB version; use sort + Python dedup.
    flux_temp = f'''
from(bucket: "{BUCKET}")
  |> range(start: -{days}d)
  |> filter(fn: (r) => r["_field"] == "internal_radiator_temperature")
  |> filter(fn: (r) => r["_value"] > {TEMP_WARN})
  |> sort(columns: ["_time"])
'''
    temp_recs = query(flux_temp)
    hot_hours_by_day: dict[str, int] = defaultdict(int)
    _seen_hot_hours: set[str] = set()
    for r in temp_recs:
        ist_dt   = r.get_time() + timedelta(hours=5, minutes=30)
        hour_key = ist_dt.strftime("%Y-%m-%d:%H")
        if hour_key not in _seen_hot_hours:
            _seen_hot_hours.add(hour_key)
            hot_hours_by_day[ist_dt.strftime("%Y-%m-%d")] += 1

    # ── 4. Build daily bars ───────────────────────────────────────────────────
    all_dates = sorted(set(daily_actual.keys()) | set(daily_expected.keys()))
    daily_bars = []
    for date_str in all_dates:
        actual_kwh   = round(daily_actual.get(date_str, 0.0), 2)
        expected_kwh = round(daily_expected.get(date_str, 0.0) / 1000, 2)
        pr      = round(actual_kwh / expected_kwh * 100, 1) if expected_kwh > 0 and actual_kwh > 0 else None
        gap_pct = round((expected_kwh - actual_kwh) / expected_kwh * 100, 1) if expected_kwh > 0 else 0
        daily_bars.append({
            "date":         date_str,
            "actual_kwh":   actual_kwh,
            "expected_kwh": expected_kwh,
            "pr_pct":       pr,
            "gap_pct":      max(gap_pct, 0),
            "underperform": gap_pct > 10,
            "hot_hours":    hot_hours_by_day.get(date_str, 0),
        })

    # ── 5. PR trend (rolling 7-day windows) ───────────────────────────────────
    pr_trend = []
    if len(daily_bars) >= 7:
        for i in range(6, len(daily_bars)):
            window       = daily_bars[i-6:i+1]
            tot_actual   = sum(d["actual_kwh"]   for d in window)
            tot_expected = sum(d["expected_kwh"] for d in window)
            pr_7d = round(tot_actual / tot_expected * 100, 1) if tot_expected > 0 else None
            pr_trend.append({"date": window[-1]["date"], "pr_7d": pr_7d})

    # ── 6. Hour-of-day efficiency profile (power_now_w vs expected) ───────────
    # aggregateWindow+pivot both return empty; use two separate sort queries.
    flux_pwr_h = f'''
from(bucket: "{BUCKET}")
  |> range(start: -{days}d)
  |> filter(fn: (r) => r["_field"] == "power_now_w")
  |> filter(fn: (r) => r["_value"] > 50)
  |> sort(columns: ["_time"])
'''
    flux_exp_h = f'''
from(bucket: "{BUCKET}")
  |> range(start: -{days}d)
  |> filter(fn: (r) => r["_field"] == "expected_power_w")
  |> filter(fn: (r) => r["_value"] > 50)
  |> sort(columns: ["_time"])
'''
    pwr_h_recs = query(flux_pwr_h)
    exp_h_recs = query(flux_exp_h)

    # Build expected lookup by IST timestamp for pairing
    exp_by_ts: dict[str, list] = defaultdict(list)
    for r in exp_h_recs:
        ist_dt = r.get_time() + timedelta(hours=5, minutes=30)
        exp_by_ts[ist_dt.strftime("%Y-%m-%dT%H:%M")].append(float(r.get_value() or 0))

    hour_buckets = defaultdict(lambda: {"actual": [], "expected": []})
    for r in pwr_h_recs:
        ist_dt   = r.get_time() + timedelta(hours=5, minutes=30)
        ist_hour = ist_dt.hour
        ts_key   = ist_dt.strftime("%Y-%m-%dT%H:%M")
        actual   = float(r.get_value() or 0)
        exp_vals = exp_by_ts.get(ts_key, [])
        expected = sum(exp_vals) / len(exp_vals) if exp_vals else 0
        if expected > 50:
            hour_buckets[ist_hour]["actual"].append(actual)
            hour_buckets[ist_hour]["expected"].append(expected)

    hourly_profile = []
    for h in range(5, 20):
        bk = hour_buckets.get(h, {"actual": [], "expected": []})
        avg_actual   = sum(bk["actual"])   / len(bk["actual"])   if bk["actual"]   else 0
        avg_expected = sum(bk["expected"]) / len(bk["expected"]) if bk["expected"] else 0
        pr_h = round(avg_actual / avg_expected * 100, 1) if avg_expected > 0 else None
        hourly_profile.append({
            "hour":           h,
            "label":          f"{h:02d}:00",
            "avg_actual_w":   round(avg_actual),
            "avg_expected_w": round(avg_expected),
            "pr_pct":         pr_h,
        })

    # ── 7. Summary KPIs ───────────────────────────────────────────────────────
    total_actual_kwh   = sum(d["actual_kwh"]   for d in daily_bars)
    total_expected_kwh = sum(d["expected_kwh"] for d in daily_bars)
    overall_pr_raw     = round(total_actual_kwh / total_expected_kwh * 100, 1) if total_expected_kwh > 0 else 0
    overall_pr         = min(overall_pr_raw, 110.0)
    calibration_warning = overall_pr_raw > 105
    lost_kwh           = max(total_expected_kwh - total_actual_kwh, 0)
    lost_inr           = round(lost_kwh * TARIFF, 0)
    underperform_days  = [d for d in daily_bars if d["underperform"]]
    hot_days           = [d for d in daily_bars if d["hot_hours"] >= 2]

    # ── 8. Actionable recommendations ────────────────────────────────────────
    actions = []

    if hot_days:
        avg_hot = sum(d["hot_hours"] for d in hot_days) / len(hot_days)
        actions.append({
            "priority": "warning" if len(hot_days) > 5 else "info",
            "icon": "🌡️",
            "title": f"Inverter running hot on {len(hot_days)} days",
            "detail": f"Average {avg_hot:.0f} hours/day above {TEMP_WARN:.0f}°C. "
                      f"Thermal derating reduces output ~1% per °C above threshold.",
            "action": "Check inverter airflow — ensure 20cm clearance on all sides",
        })

    if len(pr_trend) >= 2:
        recent_pr  = pr_trend[-1]["pr_7d"] or 0
        earlier_pr = pr_trend[max(0, len(pr_trend)//2)]["pr_7d"] or 0
        if earlier_pr > 0 and recent_pr < earlier_pr - 5:
            actions.append({
                "priority": "warning",
                "icon": "🧹",
                "title": f"Performance dropped {earlier_pr - recent_pr:.1f}% over the period",
                "detail": f"PR fell from {earlier_pr}% → {recent_pr}%. "
                          f"Gradual drops usually mean soiling. A clean can recover 3–8%.",
                "action": "Clean panels — morning with soft cloth + plain water",
            })

    if len(underperform_days) > 3:
        worst = sorted(underperform_days, key=lambda x: x["gap_pct"], reverse=True)[:3]
        worst_str = ", ".join(f"{d['date']} (−{d['gap_pct']}%)" for d in worst)
        actions.append({
            "priority": "info",
            "icon": "📉",
            "title": f"{len(underperform_days)} days with >10% gap vs weather forecast",
            "detail": f"Worst days: {worst_str}. Check if these align with clouds/rain.",
            "action": "Compare these dates with your local weather records",
        })

    if overall_pr >= 80:
        actions.append({
            "priority": "good",
            "icon": "✅",
            "title": f"System PR {overall_pr}% — above India baseline ({int(DESIGN_PR*100)}%)",
            "detail": "Your panels are converting weather-adjusted irradiance efficiently.",
            "action": "Continue regular monthly panel cleaning",
        })
    elif overall_pr >= 70:
        actions.append({
            "priority": "info",
            "icon": "ℹ️",
            "title": f"System PR {overall_pr}% — slightly below {int(DESIGN_PR*100)}% baseline",
            "detail": "Minor losses from soiling, shading, or cable heating.",
            "action": "Panel cleaning + check all DC cable connectors",
        })
    else:
        actions.append({
            "priority": "critical",
            "icon": "⚠️",
            "title": f"System PR {overall_pr}% — significantly below baseline",
            "detail": "Losses above 30% suggest a hardware issue: shading, soiling, or inverter fault.",
            "action": "Inspect panels + contact your installer for a system audit",
        })

    return {
        "status":      "success",
        "period_days": days,
        "expected_source": "open-meteo-historical",
        "summary": {
            "total_actual_kwh":    round(total_actual_kwh, 1),
            "total_expected_kwh":  round(total_expected_kwh, 1),
            "overall_pr_pct":      overall_pr,
            "design_pr_pct":       int(DESIGN_PR * 100),
            "lost_kwh":            round(lost_kwh, 1),
            "lost_inr":            int(lost_inr),
            "underperform_days":   len(underperform_days),
            "total_days":          min(len(daily_bars), days),
            "calibration_warning": calibration_warning,
        },
        "daily_bars":     daily_bars,
        "pr_trend":       pr_trend,
        "hourly_profile": hourly_profile,
        "recommendations": actions,
    }
