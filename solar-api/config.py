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


# ── UHBVN (Uttar Haryana Bijli Vitran Nigam) domestic tariff slabs ────────────
# Applicable to: Karnal, Panipat, Ambala, Yamuna Nagar, Kurukshetra, Sonipat etc.
# Source: HERC tariff order FY 2024-25. Fixed/demand charges excluded
# (those are the same with or without solar — only energy units change).
# Verify latest rates at: https://www.uhbvn.org.in/tariff
UHBVN_SLABS = [
    (100,  2.50),   # 0–100 units  @ ₹2.50/kWh
    (200,  5.25),   # 101–300 units @ ₹5.25/kWh
    (200,  6.50),   # 301–500 units @ ₹6.50/kWh
    (None, 7.00),   # >500 units    @ ₹7.00/kWh
]

def calculate_uhbvn_bill(units_kwh: float) -> float:
    """Return electricity bill in INR for given kWh under UHBVN domestic slab rates."""
    bill = 0.0
    remaining = units_kwh
    for slab_size, rate in UHBVN_SLABS:
        if remaining <= 0:
            break
        if slab_size is None:
            bill += remaining * rate
            remaining = 0
        else:
            consumed = min(remaining, slab_size)
            bill += consumed * rate
            remaining -= consumed
    return round(bill, 2)

def solar_bill_savings(monthly_kwh_generated: float, monthly_kwh_consumed: float) -> dict:
    """
    Calculate real rupee savings using UHBVN slab rates.
    Solar generation offsets the most expensive slabs first (highest-tariff units).
    Returns bill_without_solar, bill_with_solar, savings, effective_rate.
    """
    bill_without = calculate_uhbvn_bill(monthly_kwh_consumed)
    net_consumption = max(0, monthly_kwh_consumed - monthly_kwh_generated)
    bill_with = calculate_uhbvn_bill(net_consumption)
    savings = round(bill_without - bill_with, 2)
    effective_rate = round(savings / monthly_kwh_generated, 2) if monthly_kwh_generated > 0 else 0
    return {
        "bill_without_solar_inr":     bill_without,
        "bill_with_solar_inr":        bill_with,
        "savings_inr":                savings,
        "effective_rate_inr_per_kwh": effective_rate,
        "monthly_kwh_generated":      round(monthly_kwh_generated, 1),
        "monthly_kwh_consumed":       round(monthly_kwh_consumed, 1),
        "distributor":                "UHBVN",
    }


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
