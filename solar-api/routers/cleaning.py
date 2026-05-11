"""
Panel cleaning tracker.
- POST /api/cleaning      — log a cleaning event
- GET  /api/cleaning      — list all cleaning events with before/after efficiency impact
- GET  /api/cleaning/next — when to clean next based on efficiency trend

Cleaning events stored in /app/data/cleaning_log.json (lightweight, <1KB per entry).
Efficiency impact computed from real InfluxDB data: 7-day window before vs after.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional, Dict, Any
from datetime import datetime, timezone, timedelta, date
from pathlib import Path
import json

from influx import query
from config import settings

router = APIRouter(prefix="/api/cleaning", tags=["Cleaning"])

CLEANING_LOG = Path("/app/data/cleaning_log.json")
BUCKET       = settings.influxdb_bucket
WINDOW_DAYS  = 7   # compare 7 days before vs 7 days after


# ── Models ────────────────────────────────────────────────────────────────────

class CleaningEvent(BaseModel):
    date:  str           # ISO date YYYY-MM-DD
    notes: Optional[str] = None


# ── Storage helpers ───────────────────────────────────────────────────────────

def _load_log() -> list[dict]:
    try:
        if CLEANING_LOG.exists():
            return json.loads(CLEANING_LOG.read_text())
    except Exception:
        pass
    return []

def _save_log(log: list[dict]):
    CLEANING_LOG.parent.mkdir(parents=True, exist_ok=True)
    CLEANING_LOG.write_text(json.dumps(log, indent=2))


# ── Efficiency measurement ────────────────────────────────────────────────────

def _avg_efficiency(start: str, stop: str) -> float | None:
    """
    Average (actual_power / expected_power) for clear-sky daytime hours
    (expected > 200W, radiation > 300 W/m²) in the given date range.
    Returns None if insufficient data.
    """
    flux = f'''
from(bucket: "{BUCKET}")
  |> range(start: {start}T00:00:00Z, stop: {stop}T23:59:59Z)
  |> filter(fn: (r) => r["_field"] == "power_now_w" or
                        r["_field"] == "expected_power_w" or
                        r["_field"] == "shortwave_radiation_wm2")
  |> aggregateWindow(every: 1h, fn: mean, createEmpty: false)
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
  |> filter(fn: (r) => r["expected_power_w"] > 200.0 and r["shortwave_radiation_wm2"] > 300.0)
'''
    recs = query(flux)
    if len(recs) < 10:  # need at least 10 clear-sky hours for a meaningful average
        return None

    ratios = []
    for r in recs:
        actual   = r.values.get("power_now_w") or 0
        expected = r.values.get("expected_power_w") or 0
        if expected > 0:
            ratios.append(min(actual / expected, 1.05))

    return round(sum(ratios) / len(ratios) * 100, 1) if ratios else None


def _enrich_event(event: dict) -> dict:
    """Add before/after efficiency and computed impact to a cleaning event dict."""
    clean_date = event["date"]
    dt = datetime.fromisoformat(clean_date)

    before_start = (dt - timedelta(days=WINDOW_DAYS)).date().isoformat()
    before_stop  = (dt - timedelta(days=1)).date().isoformat()
    after_start  = (dt + timedelta(days=1)).date().isoformat()
    after_stop   = (dt + timedelta(days=WINDOW_DAYS)).date().isoformat()
    today_str    = date.today().isoformat()

    eff_before = _avg_efficiency(before_start, before_stop)
    eff_after  = _avg_efficiency(after_start, min(after_stop, today_str))

    gain_pct      = None
    gain_inr_month = None

    if eff_before is not None and eff_after is not None:
        gain_pct = round(eff_after - eff_before, 1)
        # Estimate monthly rupee gain: capacity × avg_irradiance_hours × gain_fraction × tariff × 30 days
        # Simplified: 4.5 peak sun hours/day for Karnal
        peak_sun_hours = 4.5
        monthly_gain_kwh = (
            settings.installed_capacity_w / 1000
            * peak_sun_hours * 30
            * (gain_pct / 100)
        )
        gain_inr_month = round(monthly_gain_kwh * settings.electricity_tariff_inr, 0)

    return {
        **event,
        "efficiency_before_pct": eff_before,
        "efficiency_after_pct":  eff_after,
        "efficiency_gain_pct":   gain_pct,
        "monthly_gain_inr":      gain_inr_month,
        "data_window_days":      WINDOW_DAYS,
    }


# ── Soiling degradation trend ─────────────────────────────────────────────────

def _days_since_last_clean(log: list[dict]) -> int:
    if not log:
        return 999
    last = max(log, key=lambda e: e["date"])["date"]
    return (date.today() - date.fromisoformat(last)).days


def _current_efficiency() -> float | None:
    """7-day rolling efficiency to detect current soiling level."""
    stop  = date.today().isoformat()
    start = (date.today() - timedelta(days=7)).isoformat()
    return _avg_efficiency(start, stop)


# ── Routes ────────────────────────────────────────────────────────────────────

@router.post("/")
def log_cleaning(event: CleaningEvent) -> Dict[str, Any]:
    """Record a panel cleaning. Returns the event with before-efficiency (after computed later)."""
    try:
        datetime.fromisoformat(event.date)
    except ValueError:
        raise HTTPException(status_code=400, detail="date must be YYYY-MM-DD")

    log = _load_log()
    entry = {"date": event.date, "notes": event.notes or ""}
    log.append(entry)
    log.sort(key=lambda e: e["date"])
    _save_log(log)

    return {"status": "logged", "event": _enrich_event(entry)}


@router.get("/")
def get_cleaning_history() -> Dict[str, Any]:
    """List all cleaning events with real before/after efficiency impact from InfluxDB."""
    log = _load_log()
    enriched = [_enrich_event(e) for e in log]
    enriched.sort(key=lambda e: e["date"], reverse=True)

    days_since = _days_since_last_clean(log)
    current_eff = _current_efficiency()

    # Recommend cleaning if: >45 days since last clean, OR current efficiency <82%
    needs_cleaning = days_since > 45 or (current_eff is not None and current_eff < 82.0)
    urgency = "high" if (days_since > 60 or (current_eff and current_eff < 75)) else (
        "medium" if needs_cleaning else "low"
    )

    return {
        "status":              "success",
        "days_since_cleaning": days_since,
        "current_efficiency_pct": current_eff,
        "cleaning_recommended":   needs_cleaning,
        "urgency":             urgency,
        "history":             enriched,
    }


@router.get("/next")
def get_next_cleaning() -> Dict[str, Any]:
    """Predict when next cleaning is needed based on current efficiency trend."""
    log      = _load_log()
    days     = _days_since_last_clean(log)
    eff      = _current_efficiency()

    # If efficiency is measurable, compute rupee cost of delay
    loss_inr_per_day = 0.0
    if eff is not None and eff < 90.0:
        loss_fraction     = (90.0 - eff) / 100.0  # efficiency gap vs 90% clean baseline
        peak_sun_hours    = 4.5
        daily_loss_kwh    = settings.installed_capacity_w / 1000 * peak_sun_hours * loss_fraction
        loss_inr_per_day  = round(daily_loss_kwh * settings.electricity_tariff_inr, 1)

    days_to_next = max(0, 60 - days)  # standard 60-day cycle

    # Override if efficiency is already poor
    if eff is not None and eff < 78.0:
        days_to_next = 0  # clean now
    elif eff is not None and eff < 82.0:
        days_to_next = min(days_to_next, 7)

    next_date = (date.today() + timedelta(days=days_to_next)).isoformat()

    return {
        "status":                "success",
        "days_since_last_clean": days,
        "current_efficiency_pct": eff,
        "recommended_clean_date": next_date,
        "days_until_next_clean": days_to_next,
        "current_loss_inr_per_day": loss_inr_per_day,
        "note": (
            "Clean immediately — efficiency significantly degraded."
            if days_to_next == 0 else
            f"Schedule cleaning within {days_to_next} days."
        )
    }
