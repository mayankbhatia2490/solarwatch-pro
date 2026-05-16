"""
Commissioning API — register new solar sites for B2B multi-tenant operation.
Each site gets its own site_id tag in InfluxDB; the collector reads SITE_ID from .env.
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from pathlib import Path
import json

router = APIRouter(prefix="/api/sites", tags=["B2B Sites"])

_SITES_FILE = Path("/app/data/sites.json")


def _load_sites() -> dict:
    try:
        if _SITES_FILE.exists():
            return json.loads(_SITES_FILE.read_text())
    except Exception:
        pass
    return {}


def _save_sites(sites: dict) -> None:
    _SITES_FILE.parent.mkdir(parents=True, exist_ok=True)
    _SITES_FILE.write_text(json.dumps(sites, indent=2))


class SiteCredentials(BaseModel):
    username: str
    password: str
    company_key: str
    pn: str
    sn: str
    devcode: str = "1"


class SiteCreate(BaseModel):
    site_id: str
    plant_id: str
    shinemonitor_credentials: SiteCredentials
    capacity_w: float = 3400.0
    install_date: str = "2025-04-17"
    customer_name: str
    location_name: str
    latitude: float = 29.6857
    longitude: float = 76.9905
    timezone: str = "Asia/Kolkata"
    tariff_per_kwh: float = 6.5
    system_cost_inr: float = 220000.0
    distributor: str = "UHBVN"
    notes: Optional[str] = None


@router.post("")
def create_site(body: SiteCreate):
    """Register a new site for monitoring. Credentials stored locally — never logged."""
    sites = _load_sites()
    if body.site_id in sites:
        raise HTTPException(status_code=409, detail=f"Site '{body.site_id}' already exists.")

    sites[body.site_id] = {
        "site_id":         body.site_id,
        "plant_id":        body.plant_id,
        "credentials":     body.shinemonitor_credentials.model_dump(),
        "capacity_w":      body.capacity_w,
        "install_date":    body.install_date,
        "customer_name":   body.customer_name,
        "location_name":   body.location_name,
        "latitude":        body.latitude,
        "longitude":       body.longitude,
        "timezone":        body.timezone,
        "tariff_per_kwh":  body.tariff_per_kwh,
        "system_cost_inr": body.system_cost_inr,
        "distributor":     body.distributor,
        "notes":           body.notes,
        "status":          "pending",
    }
    _save_sites(sites)

    return {
        "site_id": body.site_id,
        "customer_name": body.customer_name,
        "status": "registered",
        "message": (
            f"Site '{body.site_id}' registered. "
            f"Deploy a collector with SITE_ID={body.site_id} to start data collection. "
            f"First data expected within 5 minutes of collector startup."
        ),
        "next_steps": [
            f"Set SITE_ID={body.site_id} in the collector .env",
            "Run: docker compose up -d solar-collector",
            f"Query with header: X-Site-ID: {body.site_id}",
        ],
    }


@router.get("")
def list_sites():
    """List all registered sites (credentials redacted)."""
    sites = _load_sites()
    result = []
    for site_id, data in sites.items():
        safe = {k: v for k, v in data.items() if k != "credentials"}
        safe["has_credentials"] = "credentials" in data
        result.append(safe)
    return {"sites": result, "total": len(result)}


@router.delete("/{site_id}")
def delete_site(site_id: str):
    """Remove a site registration (does not delete InfluxDB data)."""
    sites = _load_sites()
    if site_id not in sites:
        raise HTTPException(status_code=404, detail=f"Site '{site_id}' not found.")
    del sites[site_id]
    _save_sites(sites)
    return {"deleted": site_id, "note": "InfluxDB historical data retained."}
