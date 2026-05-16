"""
Settings router — GET /api/settings, PATCH /api/settings, GET /api/settings/branding
Persists user overrides to /app/data/settings_override.json so they
survive container restarts without requiring a rebuild.
"""
from fastapi import APIRouter
from pydantic import BaseModel
from typing import Optional
from pathlib import Path
import json

from config import settings as _env_settings

_BRANDING_FILE = Path(__file__).parent.parent / "branding.json"

router = APIRouter()

OVERRIDE_FILE = Path("/app/data/settings_override.json")

# ── Override model ─────────────────────────────────────────────────────────────

class SettingsPayload(BaseModel):
    plant_name:           Optional[str]   = None
    installation_date:    Optional[str]   = None
    installed_capacity_w: Optional[float] = None
    electricity_tariff_inr: Optional[float] = None
    system_cost_inr:      Optional[float] = None
    timezone:             Optional[str]   = None

# ── In-memory override (loaded once at startup, updated on PATCH) ──────────────

_override: dict = {}

def _load_override():
    global _override
    try:
        if OVERRIDE_FILE.exists():
            _override = json.loads(OVERRIDE_FILE.read_text())
    except Exception:
        _override = {}

def _save_override():
    try:
        OVERRIDE_FILE.parent.mkdir(parents=True, exist_ok=True)
        OVERRIDE_FILE.write_text(json.dumps(_override, indent=2))
    except Exception:
        pass

_load_override()

# ── Merged settings helper ─────────────────────────────────────────────────────

def merged() -> dict:
    """Return settings with user overrides applied over env defaults."""
    return {
        "plant_name":             _override.get("plant_name",             _env_settings.plant_name),
        "installation_date":      _override.get("installation_date",      _env_settings.installation_date),
        "installed_capacity_w":   _override.get("installed_capacity_w",   _env_settings.installed_capacity_w),
        "electricity_tariff_inr": _override.get("electricity_tariff_inr", _env_settings.electricity_tariff_inr),
        "system_cost_inr":        _override.get("system_cost_inr",        _env_settings.system_cost_inr),
        "timezone":               _override.get("timezone",               _env_settings.timezone),
        "latitude":               str(_env_settings.latitude),
        "longitude":              str(_env_settings.longitude),
    }

# ── Routes ─────────────────────────────────────────────────────────────────────

@router.get("")
async def get_settings():
    return merged()

@router.patch("")
async def update_settings(payload: SettingsPayload):
    updates = {k: v for k, v in payload.model_dump().items() if v is not None}
    _override.update(updates)
    _save_override()
    return {"ok": True, "settings": merged()}

@router.get("/branding")
async def get_branding():
    """White-label branding config — frontend reads app name, colours, support links from here."""
    try:
        return json.loads(_BRANDING_FILE.read_text())
    except Exception:
        return {
            "app_name": "SolarWatch Pro",
            "company_name": "SolarWatch",
            "primary_color": "#1B2B6B",
            "accent_color": "#C9A84C",
        }

@router.patch("/branding")
async def update_branding(updates: dict):
    """Update white-label branding fields."""
    try:
        current = json.loads(_BRANDING_FILE.read_text()) if _BRANDING_FILE.exists() else {}
        current.update(updates)
        _BRANDING_FILE.write_text(json.dumps(current, indent=2))
        return {"ok": True, "branding": current}
    except Exception as e:
        return {"ok": False, "error": str(e)}
