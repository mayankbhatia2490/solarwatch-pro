"""Shared irradiance calibration factor — read by all routers that use expected_power."""
import json, os
from datetime import datetime, timezone

_CAL_FILE = os.environ.get("CAL_FILE", "/app/irradiance_cal.json")

def calibration_factor(month: int | None = None) -> float:
    """Return monthly correction factor from irradiance_cal.json, default 1.0."""
    if month is None:
        month = datetime.now(timezone.utc).month
    try:
        with open(_CAL_FILE) as f:
            cal = json.load(f)
        return float(cal.get("correction_factors", {}).get(str(month), 1.0))
    except (FileNotFoundError, json.JSONDecodeError, ValueError):
        return 1.0

def calibration_meta() -> dict:
    """Return calibration metadata for status endpoints."""
    try:
        with open(_CAL_FILE) as f:
            cal = json.load(f)
        return {
            "winner": cal.get("winner"),
            "calibrated_at": cal.get("calibrated_at"),
            "pvgis_mape": cal.get("pvgis_mape"),
            "openmeteo_mape": cal.get("openmeteo_mape"),
            "vedas_mape": cal.get("vedas_mape"),
        }
    except (FileNotFoundError, json.JSONDecodeError):
        return {"winner": None, "calibrated_at": None}
