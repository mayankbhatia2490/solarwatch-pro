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


# ── Shinemonitor meter bias correction ───────────────────────────────────────
# Shinemonitor reports inverter AC output; UHBVN physical meter (KWHS) reads
# at the metering point and uses utility-grade calibration.
# Derived from May-2026 bill: UHBVN 437 kWh ÷ Shinemonitor 485.4 kWh = 0.900.
# Applied to daily_energy_kwh at READ time so all historical data is corrected
# without touching the raw InfluxDB values.
# Override via SHINEMONITOR_CORRECTION env var when new bills give a better estimate.
def actual_kwh(raw_shinemonitor_kwh: float) -> float:
    """Convert Shinemonitor-reported kWh to utility-meter-equivalent kWh."""
    from config import settings
    return raw_shinemonitor_kwh * settings.shinemonitor_correction
