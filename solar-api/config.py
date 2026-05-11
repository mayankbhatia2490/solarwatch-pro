import os
from pydantic_settings import BaseSettings
from pathlib import Path
import json

class Settings(BaseSettings):
    influxdb_url: str = "http://influxdb:8086"
    influxdb_token: str = ""
    influxdb_org: str = "solar"
    influxdb_bucket: str = "solar_metrics"

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    installed_capacity_w: float = 3500.0
    electricity_tariff_inr: float = 6.5
    system_cost_inr: float = 220000.0
    installation_date: str = "2025-04-17"
    plant_name: str = "My Solar System"
    latitude: str = "29.693405600010355"
    longitude: str = "76.99938211551195"
    timezone: str = "Asia/Kolkata"

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()

# ── Runtime overrides (written by /api/settings PATCH) ────────────────────────
# These shadow the env values without requiring a container rebuild.

_OVERRIDE_FILE = Path("/app/data/settings_override.json")

def _load_overrides():
    try:
        if _OVERRIDE_FILE.exists():
            data = json.loads(_OVERRIDE_FILE.read_text())
            for k, v in data.items():
                if hasattr(settings, k) and v is not None:
                    object.__setattr__(settings, k, type(getattr(settings, k))(v))
    except Exception:
        pass

_load_overrides()
