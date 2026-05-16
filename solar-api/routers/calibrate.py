"""
Irradiance calibration endpoint.
GET /api/calibrate/status  — return current calibration result
GET /api/calibrate/run     — trigger fresh calibration (runs in background)
"""
from fastapi import APIRouter, BackgroundTasks
from typing import Dict, Any
import json, os

router = APIRouter(prefix="/api/calibrate", tags=["Calibration"])

CAL_FILE = os.environ.get("CAL_FILE", "/app/irradiance_cal.json")
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


@router.get("/status")
async def calibration_status() -> Dict[str, Any]:
    """Return the most recent calibration result."""
    if _running:
        return {"status": "running"}
    try:
        with open(CAL_FILE) as f:
            cal = json.load(f)
        cal["status"] = "ok"
        return cal
    except FileNotFoundError:
        return {"status": "not_run", "message": "Call /api/calibrate/run to start"}


@router.post("/run")
async def trigger_calibration(background_tasks: BackgroundTasks) -> Dict[str, Any]:
    """Trigger a fresh calibration in the background."""
    global _running
    if _running:
        return {"status": "already_running"}
    background_tasks.add_task(_run_cal)
    return {"status": "started", "message": "Calibration running — check /api/calibrate/status"}
