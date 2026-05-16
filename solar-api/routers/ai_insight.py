"""
AI-powered solar analysis — GET /api/ai/insight
Sends real InfluxDB data + cleaning history to Gemini 1.5 Flash and returns
a plain-English diagnostic report. Uses the free Gemini tier (15 RPM, 1M tokens/day).
Requires GEMINI_API_KEY in .env — get one free at https://aistudio.google.com/app/apikey
"""
from fastapi import APIRouter, HTTPException
from typing import Dict, Any
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import httpx

from influx import query
from config import settings
from cal_utils import calibration_factor

router = APIRouter(prefix="/api/ai", tags=["AI Insight"])

BUCKET     = settings.influxdb_bucket
CAPACITY_W = settings.installed_capacity_w
DESIGN_PR  = 0.78
TEMP_WARN  = 65.0

_GEMINI_BASE = "https://generativelanguage.googleapis.com"

# In-process cache so we only probe the models list once per container lifetime
_resolved_model: str | None = None

# Preferred model names in order — first one that exists wins
_MODEL_PREFERENCES = [
    "gemini-2.5-flash",
    "gemini-2.5-flash-preview-05-20",
    "gemini-2.5-flash-preview-04-17",
    "gemini-2.0-flash",
    "gemini-2.0-flash-001",
    "gemini-2.0-flash-lite",
    "gemini-1.5-flash-latest",
    "gemini-1.5-flash",
]

async def _resolve_model() -> str:
    """
    Return the best available Gemini model for this API key.
    Calls the models-list endpoint once, then caches the result.
    Falls back to the configured gemini_model setting if discovery fails.
    """
    global _resolved_model
    if _resolved_model:
        return _resolved_model

    # If user explicitly set a non-default model, trust it and skip discovery
    known_defaults = {"gemini-2.0-flash", "gemini-2.0-flash-001", "gemini-1.5-flash"}
    if settings.gemini_model not in known_defaults:
        _resolved_model = settings.gemini_model
        return _resolved_model

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{_GEMINI_BASE}/v1beta/models?key={settings.gemini_api_key}"
            )
            if resp.status_code != 200:
                _resolved_model = settings.gemini_model
                return _resolved_model
            data = resp.json()
            available = {m["name"].split("/")[-1] for m in data.get("models", [])}

        for preferred in _MODEL_PREFERENCES:
            if preferred in available:
                _resolved_model = preferred
                return _resolved_model
    except Exception:
        pass

    _resolved_model = settings.gemini_model
    return _resolved_model

def _gemini_url(model: str) -> str:
    return f"{_GEMINI_BASE}/v1beta/models/{model}:generateContent"


def _build_context(days: int) -> dict:
    """Pull data from InfluxDB and return a structured context dict."""

    # ── Hourly data for the period ────────────────────────────────────────────
    flux = f'''
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
    recs = query(flux)

    daily = defaultdict(lambda: {"actual_wh": 0.0, "expected_wh": 0.0,
                                  "hours": 0, "hot_hours": 0})
    hour_buckets = defaultdict(lambda: {"actual": [], "expected": []})

    for r in recs:
        t = r.get_time()
        ist = t + timedelta(hours=5, minutes=30)
        date_str = ist.strftime("%Y-%m-%d")
        h = ist.hour
        actual   = float(r.values.get("power_now_w", 0) or 0)
        expected = float(r.values.get("expected_power_w", 0) or 0)
        temp     = float(r.values.get("internal_radiator_temperature", 0) or 0)

        if expected > 50:
            month = int(date_str[5:7])
            cal   = calibration_factor(month)
            daily[date_str]["actual_wh"]   += actual
            daily[date_str]["expected_wh"] += expected * cal
            daily[date_str]["hours"]       += 1
            if temp > TEMP_WARN:
                daily[date_str]["hot_hours"] += 1
            hour_buckets[h]["actual"].append(actual)
            hour_buckets[h]["expected"].append(expected)

    daily_bars = []
    for ds in sorted(daily.keys()):
        d = daily[ds]
        a = round(d["actual_wh"] / 1000, 2)
        e = round(d["expected_wh"] / 1000, 2)
        pr = round(a / e * 100, 1) if e > 0 else None
        gap = round((e - a) / e * 100, 1) if e > 0 else 0
        daily_bars.append({
            "date": ds, "actual_kwh": a, "expected_kwh": e,
            "pr_pct": pr, "gap_pct": max(gap, 0),
            "hot_hours": d["hot_hours"],
        })

    total_actual   = sum(d["actual_kwh"]   for d in daily_bars)
    total_expected = sum(d["expected_kwh"] for d in daily_bars)
    overall_pr     = round(total_actual / total_expected * 100, 1) if total_expected > 0 else 0
    lost_kwh       = max(total_expected - total_actual, 0)
    underperform   = [d for d in daily_bars if d["gap_pct"] > 10]
    hot_days       = [d for d in daily_bars if d["hot_hours"] >= 2]

    # PR trend (rolling 7-day)
    pr_trend = []
    if len(daily_bars) >= 7:
        for i in range(6, len(daily_bars)):
            w = daily_bars[i-6:i+1]
            ta = sum(x["actual_kwh"]   for x in w)
            te = sum(x["expected_kwh"] for x in w)
            pr_trend.append({
                "date": w[-1]["date"],
                "pr_7d": round(ta / te * 100, 1) if te > 0 else None,
            })

    # Hourly profile — find hours with biggest efficiency gaps
    hourly_gaps = []
    for h in range(5, 20):
        bk = hour_buckets.get(h, {"actual": [], "expected": []})
        if bk["expected"]:
            avg_a = sum(bk["actual"]) / len(bk["actual"])
            avg_e = sum(bk["expected"]) / len(bk["expected"])
            pr_h  = round(avg_a / avg_e * 100, 1) if avg_e > 0 else None
            hourly_gaps.append({"hour": h, "pr_pct": pr_h, "avg_expected_w": round(avg_e)})

    return {
        "daily_bars": daily_bars,
        "pr_trend": pr_trend,
        "hourly_gaps": hourly_gaps,
        "summary": {
            "total_actual_kwh":   round(total_actual, 1),
            "total_expected_kwh": round(total_expected, 1),
            "overall_pr_pct":     overall_pr,
            "lost_kwh":           round(lost_kwh, 1),
            "lost_inr":           int(lost_kwh * settings.electricity_tariff_inr),
            "underperform_days":  len(underperform),
            "total_days":         len(daily_bars),
            "hot_days":           len(hot_days),
            "avg_hot_hours":      round(
                sum(d["hot_hours"] for d in hot_days) / len(hot_days), 1
            ) if hot_days else 0,
        },
    }


def _build_prompt(ctx: dict, cleaning_history: list, days: int) -> str:
    s = ctx["summary"]
    pr_trend = ctx["pr_trend"]

    # Summarise PR trend direction
    if len(pr_trend) >= 4:
        first_pr = pr_trend[0]["pr_7d"] or 0
        last_pr  = pr_trend[-1]["pr_7d"] or 0
        trend_str = (
            f"trending UP from {first_pr}% → {last_pr}%"
            if last_pr > first_pr + 2 else
            f"trending DOWN from {first_pr}% → {last_pr}%"
            if last_pr < first_pr - 2 else
            f"stable around {last_pr}%"
        )
    else:
        trend_str = f"insufficient trend data (only {len(pr_trend)} data points)"

    # Hourly gaps — worst 3 hours
    worst_hours = sorted(
        [h for h in ctx["hourly_gaps"] if h["pr_pct"] is not None],
        key=lambda x: x["pr_pct"]
    )[:3]
    hourly_str = ", ".join(
        f"{h['hour']:02d}:00 ({h['pr_pct']}% PR, expected {h['avg_expected_w']}W)"
        for h in worst_hours
    ) or "no hourly data"

    # Cleaning summary
    if cleaning_history:
        clean_strs = []
        for ev in cleaning_history[-5:]:   # last 5 events
            gain = ev.get("efficiency_gain_pct")
            gain_str = f", gain +{gain}%" if gain and gain > 0 else (
                f", no measurable gain" if gain is not None else ", impact pending"
            )
            clean_strs.append(
                f"  • {ev['date']} ({ev.get('type','manual')}){gain_str}"
                + (f": {ev['notes']}" if ev.get('notes') else "")
            )
        cleaning_str = "\n".join(clean_strs)
    else:
        cleaning_str = "  No cleaning events logged yet"

    return f"""You are a solar energy diagnostic assistant for a residential rooftop system in Karnal, Haryana, India.

SYSTEM SPECIFICATIONS:
- Inverter: KSY 3.4kW-1Ph (single-phase, single MPPT, 3400W rated)
- Panels: 6 × Vikram Solar HyperSol 595W = 3,570W DC total
- Location: Karnal, Haryana (29.69°N, 76.99°E) — hot semi-arid climate
- Electricity distributor: UHBVN, tariff ≈ ₹6.50/unit
- Installation date: April 17, 2025

PERFORMANCE SUMMARY (last {days} days, weather-adjusted):
- Overall Performance Ratio (PR): {s['overall_pr_pct']}%  (India rooftop baseline = 78%)
- Actual generation:    {s['total_actual_kwh']} kWh
- Weather-expected:     {s['total_expected_kwh']} kWh
- Generation gap:       {s['lost_kwh']} kWh  ≈ ₹{s['lost_inr']} lost revenue
- Underperforming days: {s['underperform_days']} / {s['total_days']} (>10% gap vs weather forecast)
- PR trend (rolling 7-day): {trend_str}

THERMAL DATA:
- Days with inverter temperature >65°C: {s['hot_days']}
- Average hot hours per such day: {s['avg_hot_hours']}h
(Note: KSY inverters start thermal derating above ~50°C. Karnal summers regularly exceed 45°C ambient.)

HOURLY EFFICIENCY PROFILE (worst performing hours):
{hourly_str}

PANEL CLEANING LOG (last {days} days):
{cleaning_str}

INSTRUCTIONS:
Based on this real sensor data, produce a concise solar health report in these 4 sections:

### System Health Overview
2-3 sentences: overall verdict on how well the system is performing and why.

### Key Issues Detected
Bullet list of the most likely causes of any underperformance, ordered by probable impact. Be specific (e.g. "morning shading 06:00-08:00 suggests a nearby obstruction to the east" rather than "possible shading"). If everything looks good, say so.

### Priority Actions (this week → this month → optional)
3-5 specific actions the homeowner should take, with realistic expected gains in % PR or ₹/month.

### What to Watch For
1-2 things to monitor in the next 2-4 weeks given current season and trends.

Keep it under 450 words. Use Indian context (monsoon timing, dust season, summer heat). Avoid generic solar advice — be specific to this data."""


@router.get("/models")
async def list_gemini_models() -> Dict[str, Any]:
    """Lists available Gemini models for the configured API key. Useful for diagnostics."""
    if not settings.gemini_api_key:
        raise HTTPException(status_code=503, detail="GEMINI_API_KEY not configured.")
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(
                f"{_GEMINI_BASE}/v1beta/models?key={settings.gemini_api_key}"
            )
            resp.raise_for_status()
            data = resp.json()
        models = [m["name"].split("/")[-1] for m in data.get("models", [])]
        flash  = [m for m in models if "flash" in m.lower()]
        resolved = await _resolve_model()
        return {"available_flash_models": flash, "all_models": models, "will_use": resolved}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/insight")
async def get_ai_insight(days: int = 30) -> Dict[str, Any]:
    """
    Generates an AI-powered diagnostic report using Gemini 1.5 Flash.
    Requires GEMINI_API_KEY to be set. Returns cached prompt context + AI text.
    """
    if not settings.gemini_api_key:
        raise HTTPException(
            status_code=503,
            detail="Gemini API key not configured. Add GEMINI_API_KEY to your .env file. "
                   "Get a free key at https://aistudio.google.com/app/apikey"
        )

    days = min(max(days, 7), 90)

    # Gather data
    ctx = _build_context(days)

    # Get cleaning history
    from pathlib import Path
    import json as _json
    cleaning_log_path = Path("/app/data/cleaning_log.json")
    cleaning_history = []
    try:
        if cleaning_log_path.exists():
            cleaning_history = _json.loads(cleaning_log_path.read_text())
    except Exception:
        pass

    prompt = _build_prompt(ctx, cleaning_history, days)
    model  = await _resolve_model()

    # Call Gemini
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.3,
            "maxOutputTokens": 2048,
            "topP": 0.8,
        },
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{_gemini_url(model)}?key={settings.gemini_api_key}",
                json=payload,
            )
            if resp.status_code == 400:
                raise HTTPException(status_code=400, detail=f"Gemini API error: {resp.text}")
            if resp.status_code == 403:
                raise HTTPException(status_code=403, detail="Gemini API key invalid or quota exceeded.")
            resp.raise_for_status()
            result = resp.json()
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Gemini API timed out — try again in a moment.")
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gemini API unreachable: {e}")

    try:
        ai_text = result["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError):
        raise HTTPException(status_code=502, detail=f"Unexpected Gemini response: {result}")

    return {
        "status":    "success",
        "period_days": days,
        "model":     model,
        "summary":   ctx["summary"],
        "ai_report": ai_text,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ── Suggestions endpoint ──────────────────────────────────────────────────────

def _get_current_readings() -> dict:
    """Fetch the last 24h averages and today's peak for context."""
    flux = f'''
from(bucket: "{BUCKET}")
  |> range(start: -24h)
  |> filter(fn: (r) =>
      r["_field"] == "power_now_w" or
      r["_field"] == "expected_power_w" or
      r["_field"] == "internal_radiator_temperature" or
      r["_field"] == "pv1_voltage" or
      r["_field"] == "shortwave_radiation_wm2")
  |> filter(fn: (r) => r["_value"] > 0)
  |> aggregateWindow(every: 1h, fn: mean, createEmpty: false)
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
'''
    recs = query(flux)

    temps, actual_powers, expected_powers, radiations = [], [], [], []
    peak_power = 0.0

    for r in recs:
        t_val  = float(r.values.get("internal_radiator_temperature") or 0)
        a_val  = float(r.values.get("power_now_w") or 0)
        e_val  = float(r.values.get("expected_power_w") or 0)
        rad    = float(r.values.get("shortwave_radiation_wm2") or 0)
        if t_val > 0: temps.append(t_val)
        if a_val > 0: actual_powers.append(a_val); peak_power = max(peak_power, a_val)
        if e_val > 50: expected_powers.append(e_val)
        if rad > 0: radiations.append(rad)

    avg_temp    = round(sum(temps) / len(temps), 1)        if temps          else None
    max_temp    = round(max(temps), 1)                     if temps          else None
    pr_24h      = round(sum(actual_powers) / sum(expected_powers) * 100, 1) \
                  if expected_powers and sum(expected_powers) > 0 else None
    avg_rad     = round(sum(radiations) / len(radiations)) if radiations     else None

    return {
        "avg_inverter_temp_c":  avg_temp,
        "max_inverter_temp_c":  max_temp,
        "peak_power_w":         round(peak_power),
        "capacity_w":           CAPACITY_W,
        "peak_capacity_pct":    round(peak_power / CAPACITY_W * 100, 1) if peak_power else 0,
        "pr_24h_pct":           pr_24h,
        "avg_radiation_wm2":    avg_rad,
    }


def _build_suggestions_prompt(readings: dict, pr_30d: float | None,
                               hot_days_30d: int, days_since_clean: int) -> str:
    temp_str = (
        f"avg {readings['avg_inverter_temp_c']}°C, peak {readings['max_inverter_temp_c']}°C (last 24h)"
        if readings["avg_inverter_temp_c"] else "no temperature data"
    )
    peak_str = (
        f"{readings['peak_power_w']}W — {readings['peak_capacity_pct']}% of {int(CAPACITY_W)}W capacity"
        if readings["peak_power_w"] else "no power data"
    )

    return f"""You are a solar energy optimization consultant for a residential rooftop system in Karnal, Haryana, India.

SYSTEM:
- Inverter: KSY 3.4kW-1Ph (single-phase, single MPPT)
- Panels: 6 × Vikram Solar HyperSol 595W = 3,570W DC total
- Location: Karnal, Haryana (hot semi-arid, very dusty summers, monsoon Jul-Sep)
- Installation: April 2025
- Electricity tariff: ₹6.50/unit (UHBVN)

CURRENT SENSOR DATA:
- Inverter temperature: {temp_str}
- Peak power output (last 24h): {peak_str}
- 24h Performance Ratio: {readings['pr_24h_pct']}%
- 30-day PR: {pr_30d}%
- Days with inverter >65°C in last 30 days: {hot_days_30d}
- Days since last panel cleaning: {days_since_clean}
- Avg solar irradiance (last 24h): {readings['avg_radiation_wm2']} W/m²

TASK:
Generate a JSON array of improvement suggestions tailored to this system and its current data.
Each suggestion should be a physical or operational change the homeowner can actually make.

Focus areas (cover all that are relevant based on the data):
1. Cooling the panels/inverter (white roof paint, ventilation gaps, shade cloth on inverter, etc.)
2. Panel soiling / cleaning schedule
3. Inverter placement and airflow
4. Wiring or connection losses
5. Seasonal optimisation (tilt angle for winter/summer, pre-monsoon cleaning)
6. Any other improvement relevant to this specific data

For EACH suggestion output exactly this JSON structure:
{{
  "rank": <1-based priority>,
  "category": "<thermal|soiling|shading|wiring|seasonal|operational>",
  "title": "<short name, max 6 words>",
  "problem": "<1 sentence: what sensor data shows the problem>",
  "solution": "<2 sentences: exactly what to do>",
  "expected_gain_pct": <realistic PR gain in %, number only>,
  "expected_gain_kwh_monthly": <number, based on 3.57kW system, 5h peak sun/day>,
  "expected_gain_inr_monthly": <number, at ₹6.50/unit>,
  "cost_inr": <realistic Indian market cost, number only>,
  "payback_months": <cost / monthly_gain rounded to integer>,
  "effort": "<easy|medium|complex>",
  "diy": <true if homeowner can do it themselves, false if needs professional>,
  "season": "<best season to implement, e.g. 'Before summer (March)' or 'Any time'>"
}}

Return ONLY a valid JSON array, no markdown, no explanation, no code fences. Start directly with [."""


async def _call_gemini_json(prompt: str) -> list:
    """Call Gemini in JSON mode and parse the response array."""
    import json as _json

    model = await _resolve_model()
    payload = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "temperature": 0.2,
            "maxOutputTokens": 8192,
            "topP": 0.8,
            "responseMimeType": "application/json",  # forces valid JSON, no truncation mid-string
        },
    }

    async with httpx.AsyncClient(timeout=45) as client:
        resp = await client.post(
            f"{_gemini_url(model)}?key={settings.gemini_api_key}",
            json=payload,
        )
        if resp.status_code == 403:
            raise HTTPException(status_code=403, detail="Gemini API key invalid or quota exceeded.")
        resp.raise_for_status()
        result = resp.json()

    raw = result["candidates"][0]["content"]["parts"][0]["text"].strip()
    # Strip accidental markdown fences (shouldn't happen in JSON mode, but guard anyway)
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[1].rsplit("```", 1)[0].strip()

    try:
        return _json.loads(raw)
    except _json.JSONDecodeError as e:
        raise HTTPException(
            status_code=502,
            detail=f"Gemini returned invalid JSON: {e}. First 200 chars: {raw[:200]}"
        )


@router.get("/suggestions")
async def get_ai_suggestions() -> Dict[str, Any]:
    """
    Returns a table of AI-generated improvement suggestions for the dashboard.
    Each row has problem, solution, expected gain (kWh + ₹/month), cost, payback.
    Backed by real-time inverter temperature, PR, and cleaning data.
    Requires GEMINI_API_KEY.
    """
    if not settings.gemini_api_key:
        raise HTTPException(
            status_code=503,
            detail="Gemini API key not configured. Add GEMINI_API_KEY to .env file.",
        )

    from pathlib import Path
    import json as _json

    # Current readings
    readings = _get_current_readings()

    # 30-day PR and hot days from the full context
    ctx_30 = _build_context(30)
    pr_30d    = ctx_30["summary"]["overall_pr_pct"]
    hot_days  = ctx_30["summary"]["hot_days"]

    # Days since last clean
    cleaning_log_path = Path("/app/data/cleaning_log.json")
    days_since_clean = 999
    try:
        if cleaning_log_path.exists():
            log = _json.loads(cleaning_log_path.read_text())
            if log:
                from datetime import date
                last = max(log, key=lambda e: e["date"])["date"]
                days_since_clean = (date.today() - date.fromisoformat(last)).days
    except Exception:
        pass

    prompt = _build_suggestions_prompt(readings, pr_30d, hot_days, days_since_clean)

    try:
        suggestions = await _call_gemini_json(prompt)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gemini error: {e}")

    return {
        "status":       "success",
        "model":        await _resolve_model(),
        "context":      {**readings, "pr_30d_pct": pr_30d, "hot_days_30d": hot_days,
                         "days_since_clean": days_since_clean},
        "suggestions":  suggestions,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
