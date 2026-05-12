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

    installed_capacity_w: float = 3570.0  # 6 × Vikram Solar HyperSol 595W STC
    electricity_tariff_inr: float = 6.5
    system_cost_inr: float = 220000.0
    installation_date: str = "2025-04-17"
    plant_name: str = "My Solar System"
    latitude: str = "29.693405600010355"
    longitude: str = "76.99938211551195"
    timezone: str = "Asia/Kolkata"
    location_name: str = "Karnal, Haryana"
    site_id: str = "default"

    # ── UHBVN domestic tariff slabs — configurable so rates can be updated
    # without a code change when HERC issues new orders.
    # Set these in .env or via /api/settings PATCH.
    # Verify current rates at: https://www.uhbvn.org.in/tariff
    tariff_year: str = "2025-26"
    tariff_slab1_limit: int = 100        # units; 0 → this limit at slab1 rate
    tariff_slab1_rate: float = 2.50      # ₹/unit
    tariff_slab2_limit: int = 300        # units; slab1_limit+1 → this limit
    tariff_slab2_rate: float = 5.25
    tariff_slab3_limit: int = 500
    tariff_slab3_rate: float = 6.50
    tariff_slab4_rate: float = 7.00      # 501+ units

    tariff_fuel_surcharge_per_unit: float = 0.35   # ₹/unit (variable — check latest bill)
    tariff_electricity_duty_pct: float = 5.0        # % of energy charges
    tariff_meter_rent_inr: float = 30.0             # ₹/month fixed

    # ── Consumption baseline — used for UHBVN bill savings calculation ──────────
    # Set to your actual monthly grid consumption from your electricity bill.
    monthly_consumption_kwh: float = 600.0   # ₹/month household consumption

    # ── Gemini AI — daily report analysis (free tier: 15 RPM, 1M tokens/day) ───
    # Get a free key at: https://aistudio.google.com/app/apikey
    gemini_api_key: str = ""

    class Config:
        env_file = ".env"
        extra = "ignore"

settings = Settings()


def _get_slabs() -> list[dict]:
    """Build the slab table from current settings (supports runtime updates)."""
    s = settings
    return [
        {"limit": s.tariff_slab1_limit, "rate": s.tariff_slab1_rate,
         "label": f"0–{s.tariff_slab1_limit} units"},
        {"limit": s.tariff_slab2_limit, "rate": s.tariff_slab2_rate,
         "label": f"{s.tariff_slab1_limit+1}–{s.tariff_slab2_limit} units"},
        {"limit": s.tariff_slab3_limit, "rate": s.tariff_slab3_rate,
         "label": f"{s.tariff_slab2_limit+1}–{s.tariff_slab3_limit} units"},
        {"limit": float("inf"), "rate": s.tariff_slab4_rate,
         "label": f"{s.tariff_slab3_limit+1}+ units"},
    ]


def _energy_charge(units: float) -> tuple[float, list[dict]]:
    """Return (total_energy_charge, slab_breakdown) for given units consumed."""
    slabs = _get_slabs()
    charge = 0.0
    remaining = units
    prev = 0
    breakdown = []
    for slab in slabs:
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
    Uses tariff values from settings — update .env to reflect new HERC orders.
    """
    energy_charge, breakdown = _energy_charge(units_kwh)
    fuel_surcharge    = round(units_kwh * settings.tariff_fuel_surcharge_per_unit, 2)
    electricity_duty  = round(energy_charge * settings.tariff_electricity_duty_pct / 100, 2)
    fixed             = settings.tariff_meter_rent_inr
    total             = round(energy_charge + fuel_surcharge + electricity_duty + fixed, 2)
    effective_rate    = round(total / units_kwh, 2) if units_kwh > 0 else 0.0

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
    without    = calculate_uhbvn_bill(monthly_kwh_consumed)
    net        = max(0.0, monthly_kwh_consumed - monthly_kwh_generated)
    with_solar = calculate_uhbvn_bill(net)
    savings    = round(without["total_bill"] - with_solar["total_bill"], 2)
    effective_rate = round(savings / monthly_kwh_generated, 2) if monthly_kwh_generated > 0 else 0

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
            without["energy_charge"] - with_solar["energy_charge"], 2
        ),
        "distributor":    "UHBVN",
        "tariff_year":    settings.tariff_year,
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
