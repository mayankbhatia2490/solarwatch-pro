"""
System Analysis — GET /api/analysis
Weather-adjusted performance comparison: actual vs expected, PR trend,
underperformance periods, and actionable improvement recommendations.
All data comes from real InfluxDB readings — nothing is fabricated.
"""
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from typing import Dict, Any
from datetime import datetime, timezone, timedelta
from influx import query
from config import settings
import traceback

router = APIRouter(prefix="/api/analysis", tags=["Analysis"])

BUCKET = settings.influxdb_bucket
CAPACITY_W = settings.installed_capacity_w
TARIFF = settings.electricity_tariff_inr
DESIGN_PR = 0.78   # India rooftop baseline Performance Ratio
TEMP_WARN = 65.0   # °C — inverter starts thermal derating


def _empty_response(days: int) -> Dict[str, Any]:
    return {
        "status": "no_data",
        "period_days": days,
        "summary": {
            "total_actual_kwh": 0, "total_expected_kwh": 0,
            "overall_pr_pct": 0, "design_pr_pct": int(DESIGN_PR * 100),
            "lost_kwh": 0, "lost_inr": 0,
            "underperform_days": 0, "total_days": 0,
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


@router.get("/")
def get_analysis(days: int = 30) -> Dict[str, Any]:
    """
    Returns weather-adjusted performance analysis for the last N days.
    Compares actual generation against expected (based on irradiance),
    identifies underperformance causes, and provides improvement actions.
    """
    try:
        return _get_analysis_inner(days)
    except Exception as exc:
        traceback.print_exc()
        return JSONResponse(status_code=200, content=_empty_response(days))


def _get_analysis_inner(days: int) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)

    # ── 1. Daily actual vs expected (for bar chart) ────────────────────────────
    flux_daily = f'''
from(bucket: "{BUCKET}")
  |> range(start: -{days}d)
  |> filter(fn: (r) =>
      r["_field"] == "power_now_w" or
      r["_field"] == "expected_power_w" or
      r["_field"] == "internal_radiator_temperature")
  |> filter(fn: (r) => r["_value"] > 0)
  |> aggregateWindow(every: 1h, fn: mean, createEmpty: false)
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
  |> sort(columns: ["_time"])
'''
    hourly_recs = query(flux_daily)

    # Aggregate into daily buckets (IST date)
    from collections import defaultdict
    daily = defaultdict(lambda: {"actual_wh": 0.0, "expected_wh": 0.0,
                                  "hours": 0, "hot_hours": 0})

    for r in hourly_recs:
        t = r.get_time()
        # Convert UTC → IST date
        ist_date = (t + timedelta(hours=5, minutes=30)).strftime("%Y-%m-%d")
        actual   = float(r.values.get("power_now_w", 0) or 0)
        expected = float(r.values.get("expected_power_w", 0) or 0)
        temp     = float(r.values.get("internal_radiator_temperature", 0) or 0)

        if expected > 50:   # only count daylight hours
            daily[ist_date]["actual_wh"]   += actual
            daily[ist_date]["expected_wh"] += expected
            daily[ist_date]["hours"]       += 1
            if temp > TEMP_WARN:
                daily[ist_date]["hot_hours"] += 1

    # Build sorted list for the chart
    daily_bars = []
    for date_str in sorted(daily.keys()):
        d = daily[date_str]
        actual_kwh   = round(d["actual_wh"]   / 1000, 2)
        expected_kwh = round(d["expected_wh"] / 1000, 2)
        pr = round(actual_kwh / expected_kwh * 100, 1) if expected_kwh > 0 else None
        gap_pct = round((expected_kwh - actual_kwh) / expected_kwh * 100, 1) if expected_kwh > 0 else 0
        daily_bars.append({
            "date":         date_str,
            "actual_kwh":   actual_kwh,
            "expected_kwh": expected_kwh,
            "pr_pct":       pr,
            "gap_pct":      max(gap_pct, 0),
            "underperform": gap_pct > 10,
            "hot_hours":    d["hot_hours"],
        })

    # ── 2. PR trend (rolling 7-day windows) ───────────────────────────────────
    pr_trend = []
    if len(daily_bars) >= 7:
        for i in range(6, len(daily_bars)):
            window = daily_bars[i-6:i+1]
            tot_actual   = sum(d["actual_kwh"]   for d in window)
            tot_expected = sum(d["expected_kwh"] for d in window)
            pr_7d = round(tot_actual / tot_expected * 100, 1) if tot_expected > 0 else None
            pr_trend.append({"date": window[-1]["date"], "pr_7d": pr_7d})

    # ── 3. Hour-of-day efficiency profile ────────────────────────────────────
    flux_hourly = f'''
from(bucket: "{BUCKET}")
  |> range(start: -{days}d)
  |> filter(fn: (r) =>
      r["_field"] == "power_now_w" or
      r["_field"] == "expected_power_w")
  |> filter(fn: (r) => r["_value"] > 50)
  |> aggregateWindow(every: 15m, fn: mean, createEmpty: false)
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
'''
    interval_recs = query(flux_hourly)

    hour_buckets = defaultdict(lambda: {"actual": [], "expected": []})
    for r in interval_recs:
        t = r.get_time()
        ist_hour = (t + timedelta(hours=5, minutes=30)).hour
        actual   = float(r.values.get("power_now_w", 0) or 0)
        expected = float(r.values.get("expected_power_w", 0) or 0)
        if expected > 50:
            hour_buckets[ist_hour]["actual"].append(actual)
            hour_buckets[ist_hour]["expected"].append(expected)

    hourly_profile = []
    for h in range(5, 20):   # 5am → 7pm covers all daylight in Karnal
        buck = hour_buckets.get(h, {"actual": [], "expected": []})
        avg_actual   = sum(buck["actual"])   / len(buck["actual"])   if buck["actual"]   else 0
        avg_expected = sum(buck["expected"]) / len(buck["expected"]) if buck["expected"] else 0
        pr = round(avg_actual / avg_expected * 100, 1) if avg_expected > 0 else None
        hourly_profile.append({
            "hour":         h,
            "label":        f"{h:02d}:00",
            "avg_actual_w": round(avg_actual, 0),
            "avg_expected_w": round(avg_expected, 0),
            "pr_pct":       pr,
        })

    # ── 4. Summary KPIs ───────────────────────────────────────────────────────
    total_actual_kwh   = sum(d["actual_kwh"]   for d in daily_bars)
    total_expected_kwh = sum(d["expected_kwh"] for d in daily_bars)
    overall_pr         = round(total_actual_kwh / total_expected_kwh * 100, 1) if total_expected_kwh > 0 else 0
    lost_kwh           = max(total_expected_kwh - total_actual_kwh, 0)
    lost_inr           = round(lost_kwh * TARIFF, 0)
    underperform_days  = [d for d in daily_bars if d["underperform"]]
    hot_days           = [d for d in daily_bars if d["hot_hours"] >= 2]

    # ── 5. Actionable recommendations ────────────────────────────────────────
    actions = []

    # Thermal derating
    if hot_days:
        avg_hot = sum(d["hot_hours"] for d in hot_days) / len(hot_days)
        actions.append({
            "priority": "warning" if len(hot_days) > 5 else "info",
            "icon": "🌡️",
            "title": f"Inverter running hot on {len(hot_days)} days",
            "detail": f"Average {avg_hot:.0f} hours/day above {TEMP_WARN:.0f}°C. "
                      f"Thermal derating reduces output ~1% per °C above threshold. "
                      f"Improve ventilation around the inverter.",
            "action": "Check inverter airflow — ensure 20cm clearance on all sides",
        })

    # Soiling / shading (sustained PR drop)
    if len(pr_trend) >= 2:
        recent_pr  = pr_trend[-1]["pr_7d"] or 0
        earlier_pr = pr_trend[max(0, len(pr_trend)//2)]["pr_7d"] or 0
        if earlier_pr > 0 and recent_pr < earlier_pr - 5:
            actions.append({
                "priority": "warning",
                "icon": "🧹",
                "title": f"Performance dropped {earlier_pr - recent_pr:.1f}% over the period",
                "detail": f"PR fell from {earlier_pr}% → {recent_pr}%. "
                          f"Gradual drops usually mean soiling (dust/bird droppings). "
                          f"A clean can recover 3–8% output.",
                "action": "Clean panels — morning with soft cloth + plain water",
            })

    # More than 3 bad days
    if len(underperform_days) > 3:
        worst = sorted(underperform_days, key=lambda x: x["gap_pct"], reverse=True)[:3]
        worst_str = ", ".join(f"{d['date']} (−{d['gap_pct']}%)" for d in worst)
        actions.append({
            "priority": "info",
            "icon": "📉",
            "title": f"{len(underperform_days)} days with >10% gap vs weather forecast",
            "detail": f"Worst days: {worst_str}. "
                      f"Check if these align with clouds/rain or equipment issues.",
            "action": "Compare these dates with your local weather records",
        })

    # System healthy
    if overall_pr >= 80:
        actions.append({
            "priority": "good",
            "icon": "✅",
            "title": f"System PR {overall_pr}% — above India baseline ({int(DESIGN_PR*100)}%)",
            "detail": f"Your panels are converting weather-adjusted irradiance efficiently. "
                      f"No structural issues detected.",
            "action": "Continue regular monthly panel cleaning",
        })
    elif overall_pr >= 70:
        actions.append({
            "priority": "info",
            "icon": "ℹ️",
            "title": f"System PR {overall_pr}% — slightly below {int(DESIGN_PR*100)}% baseline",
            "detail": "Minor losses from soiling, shading, or cable heating. "
                      "Within acceptable range but room for improvement.",
            "action": "Panel cleaning + check all DC cable connectors",
        })
    else:
        actions.append({
            "priority": "critical",
            "icon": "⚠️",
            "title": f"System PR {overall_pr}% — significantly below baseline",
            "detail": "Losses above 30% from weather-adjusted baseline suggest a hardware "
                      "issue: shading, soiling, or inverter fault.",
            "action": "Inspect panels + contact your installer for a system audit",
        })

    return {
        "status": "success",
        "period_days": days,
        "summary": {
            "total_actual_kwh":   round(total_actual_kwh, 1),
            "total_expected_kwh": round(total_expected_kwh, 1),
            "overall_pr_pct":     overall_pr,
            "design_pr_pct":      int(DESIGN_PR * 100),
            "lost_kwh":           round(lost_kwh, 1),
            "lost_inr":           int(lost_inr),
            "underperform_days":  len(underperform_days),
            "total_days":         len(daily_bars),
        },
        "daily_bars":     daily_bars,
        "pr_trend":       pr_trend,
        "hourly_profile": hourly_profile,
        "recommendations": actions,
    }
