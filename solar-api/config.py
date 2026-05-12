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

    installed_capacity_w: float = 3400.0
    electricity_tariff_inr: float = 6.5
    system_cost_inr: float = 220000.0
    installation_date: str = "2025-04-17"
    plant_name: str = "My Solar System"
    latitude: str = "29.693405600010355"
    longitude: str = "76.99938211551195"
    timezone: str = "Asia/Kolkata"
    location_name: str = "Karnal, Haryana"
    site_id: str = "default"

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()


# ── UHBVN domestic tariff — HERC order FY 2025-26 ────────────────────────────
# Applicable: Karnal, Panipat, Ambala, Yamuna Nagar, Kurukshetra, Sonipat
# Verify latest at: https://www.uhbvn.org.in/tariff
UHBVN_ENERGY_SLABS = [
    {"limit": 100,        "rate": 2.50, "label": "0–100 units"},
    {"limit": 300,        "rate": 5.25, "label": "101–300 units"},
    {"limit": 500,        "rate": 6.50, "label": "301–500 units"},
    {"limit": float("inf"), "rate": 7.00, "label": "501+ units"},
]

# Fixed charges that apply regardless of solar (not included in "savings"):
UHBVN_FIXED = {
    "meter_rent_inr":           30.0,    # ₹/month
    "fuel_surcharge_per_unit":   0.35,   # ₹/kWh (variable, tracks fuel cost)
    "electricity_duty_pct":      5.0,    # % of energy charges only
}

TARIFF_YEAR = "2025-26"


def _energy_charge(units: float) -> tuple[float, list[dict]]:
    """Return (total_energy_charge, slab_breakdown) for given units consumed."""
    charge = 0.0
    remaining = units
    prev = 0
    breakdown = []
    for slab in UHBVN_ENERGY_SLABS:
        if remaining <= 0:
            break
        cap = slab["limit"] - prev
        used = min(remaining, cap)
        cost = used * slab["rate"]
        if used > 0:
            breakdown.append({
                "slab": slab["label"],
                "units": round(used, 2),
                "rate_per_unit": slab["rate"],
                "charge": round(cost, 2),
            })
        charge += cost
        remaining -= used
        prev = slab["limit"] if slab["limit"] != float("inf") else prev
    return round(charge, 2), breakdown


def calculate_uhbvn_bill(units_kwh: float) -> dict:
    """
    Full UHBVN domestic bill for given kWh consumed.
    Returns total and line-item breakdown including surcharges.
    """
    energy_charge, breakdown = _energy_charge(units_kwh)
    fuel_surcharge = round(units_kwh * UHBVN_FIXED["fuel_surcharge_per_unit"], 2)
    electricity_duty = round(energy_charge * UHBVN_FIXED["electricity_duty_pct"] / 100, 2)
    fixed = UHBVN_FIXED["meter_rent_inr"]
    total = round(energy_charge + fuel_surcharge + electricity_duty + fixed, 2)
    effective_rate = round(total / units_kwh, 2) if units_kwh > 0 else 0.0

    return {
        "units_consumed":         round(units_kwh, 1),
        "energy_charge":          energy_charge,
        "fuel_surcharge":         fuel_surcharge,
        "electricity_duty":       electricity_duty,
        "fixed_charges":          fixed,
        "total_bill":             total,
        "effective_rate_per_kwh": effective_rate,
        "slab_breakdown":         breakdown,
    }


def solar_bill_savings(monthly_kwh_generated: float, monthly_kwh_consumed: float) -> dict:
    """
    Real rupee savings under UHBVN slab rates with full surcharge calculation.
    Solar offsets grid consumption — highest-tariff slabs saved first.
    """
    without = calculate_uhbvn_bill(monthly_kwh_consumed)
    net = max(0.0, monthly_kwh_consumed - monthly_kwh_generated)
    with_solar = calculate_uhbvn_bill(net)
    savings = round(without["total_bill"] - with_solar["total_bill"], 2)
    effective_rate = round(savings / monthly_kwh_generated, 2) if monthly_kwh_generated > 0 else 0

    # Identify which slabs are avoided by solar
    slab_without = without["slab_breakdown"][-1]["slab"] if without["slab_breakdown"] else "—"
    slab_with    = with_solar["slab_breakdown"][-1]["slab"] if with_solar["slab_breakdown"] else "—"

    return {
        "bill_without_solar_inr":     without["total_bill"],
        "bill_with_solar_inr":        with_solar["total_bill"],
        "savings_inr":                savings,
        "effective_rate_inr_per_kwh": effective_rate,
        "monthly_kwh_generated":      round(monthly_kwh_generated, 1),
        "monthly_kwh_consumed":       round(monthly_kwh_consumed, 1),
        "units_from_grid":            round(net, 1),
        "slab_without_solar":         slab_without,
        "slab_with_solar":            slab_with,
        "slab_benefit_inr":           round(
            (without["energy_charge"] - with_solar["energy_charge"]) -
            (without["fuel_surcharge"] - with_solar["fuel_surcharge"]) * 0, 2
        ),
        "distributor":   "UHBVN",
        "tariff_year":   TARIFF_YEAR,
        "detail_without": without,
        "detail_with":    with_solar,
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
