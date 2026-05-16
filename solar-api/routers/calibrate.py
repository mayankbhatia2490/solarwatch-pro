"""
Irradiance calibration management.
GET  /api/calibrate/status  — current calibration result + per-month factors
POST /api/calibrate/run     — trigger fresh calibration in background
POST /api/calibrate/reset   — reset all factors to 1.0 (no correction)
"""
from fastapi import APIRouter, BackgroundTasks
from typing import Dict, Any
import json, os
from datetime import datetime, timezone

router = APIRouter(prefix="/api/calibrate", tags=["Calibration"])

CAL_FILE = os.environ.get("CAL_FILE", "/app/irradiance_cal.json")

MONTH_NAMES = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]

_running = False


def _run_cal():
    global _running
    _running = True
    try:
        import sys
        sys.path.insert(0, "/app")
        from calibrate_irradiance import run_calibration
        run_calibration()
    except Exception as e:
        print(f"Calibration error: {e}")
    finally:
        _running = False


def _default_cal() -> dict:
    """Return a neutral calibration (all factors = 1.0, no source bias)."""
    return {
        "correction_factors": {str(m): 1.0 for m in range(1, 13)},
        "winner": "none",
        "calibrated_at": datetime.now(timezone.utc).isoformat(),
        "note": "Reset to neutral — no correction applied. Re-run calibration when 30+ days of data are available.",
    }


@router.get("/status")
async def calibration_status() -> Dict[str, Any]:
    """Return the most recent calibration result with per-month factor table."""
    if _running:
        return {"status": "running"}
    try:
        with open(CAL_FILE) as f:
            cal = json.load(f)
    except FileNotFoundError:
        return {"status": "not_run", "message": "No calibration file found. POST /api/calibrate/run to start."}

    factors = cal.get("correction_factors", {})
    factor_table = []
    suspicious = False
    for m in range(1, 13):
        v = float(factors.get(str(m), 1.0))
        flag = v < 0.70 or v > 1.40   # outside ±30/40% is a calibration anomaly
        if flag:
            suspicious = True
        factor_table.append({
            "month": m,
            "month_name": MONTH_NAMES[m - 1],
            "factor": round(v, 4),
            "suspicious": flag,
        })

    # Age of calibration
    age_days = None
    try:
        cal_dt = datetime.fromisoformat(cal["calibrated_at"])
        if cal_dt.tzinfo is None:
            cal_dt = cal_dt.replace(tzinfo=timezone.utc)
        age_days = (datetime.now(timezone.utc) - cal_dt).days
    except Exception:
        pass

    return {
        "status":           "ok",
        "winner":           cal.get("winner", "unknown"),
        "calibrated_at":    cal.get("calibrated_at"),
        "age_days":         age_days,
        "note":             cal.get("note", ""),
        "suspicious":       suspicious,
        "factors":          factor_table,
        "raw":              factors,
    }


@router.post("/run")
async def trigger_calibration(background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """Trigger a fresh calibration in the background. Takes ~30 seconds."""
    global _running
    if _running:
        return {"status": "already_running", "message": "Calibration already in progress."}
    background_tasks.add_task(_run_cal)
    return {"status": "started", "message": "Calibration running — poll GET /api/calibrate/status"}


@router.post("/reset")
async def reset_calibration() -> Dict[str, Any]:
    """
    Reset all monthly correction factors to 1.0 (neutral — no correction).
    Use this when the calibration file has produced anomalous factors.
    After resetting, trigger /api/calibrate/run when you have 30+ days of data.
    """
    cal = _default_cal()
    try:
        import pathlib
        pathlib.Path(CAL_FILE).parent.mkdir(parents=True, exist_ok=True)
        with open(CAL_FILE, "w") as f:
            json.dump(cal, f, indent=2)
        return {"status": "reset", "message": "All 12 monthly factors set to 1.0.", "calibration": cal}
    except Exception as e:
        return {"status": "error", "message": str(e)}
