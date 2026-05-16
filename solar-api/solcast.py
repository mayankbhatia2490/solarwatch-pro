"""
Solcast irradiance client — hobbyist plan (50 calls/day).
Strategy: fetch estimated_actuals every 30 min, forecasts every 3 h.
File cache at /app/data/solcast_cache.json survives container restarts.
Falls back to cached data when rate limit reached or API is unreachable.
"""
import os, json, requests
from datetime import datetime, timezone, date
from pathlib import Path

_API_KEY   = os.environ.get("SOLCAST_API_KEY", "")
_LAT       = float(os.environ.get("LATITUDE",  "29.6934"))
_LON       = float(os.environ.get("LONGITUDE", "76.9994"))
_TILT      = 5    # panel tilt degrees
_AZIMUTH   = 180  # Solcast API: 0=North clockwise → 180=South (panels face south in Karnal)

_CACHE_FILE        = Path("/app/data/solcast_cache.json")
_MAX_CALLS_PER_DAY = 45   # 5-call safety buffer from the 50 limit
_ACTUALS_TTL_MIN   = 30   # re-fetch current irradiance every 30 min
_FORECAST_TTL_MIN  = 180  # re-fetch 3-day forecast every 3 h

_BASE = "https://api.solcast.com.au/world_radiation"


# ── Cache helpers ─────────────────────────────────────────────────────────────

def _load() -> dict:
    try:
        if _CACHE_FILE.exists():
            return json.loads(_CACHE_FILE.read_text())
    except Exception:
        pass
    return {}


def _save(cache: dict):
    try:
        _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_FILE.write_text(json.dumps(cache, indent=2))
    except Exception:
        pass


def _age_min(iso: str | None) -> float:
    if not iso:
        return 9999.0
    try:
        t = datetime.fromisoformat(iso)
        if t.tzinfo is None:
            t = t.replace(tzinfo=timezone.utc)
        return (datetime.now(timezone.utc) - t).total_seconds() / 60
    except Exception:
        return 9999.0


def _can_call(cache: dict) -> bool:
    """Return True and increment counter if under daily limit."""
    today = date.today().isoformat()
    d = cache.get("daily", {})
    if d.get("date") != today:
        d = {"date": today, "calls": 0}
    if d["calls"] >= _MAX_CALLS_PER_DAY:
        return False
    d["calls"] += 1
    cache["daily"] = d
    return True


def _rollback_call(cache: dict):
    """Decrement counter on API failure — don't waste quota."""
    d = cache.get("daily", {})
    d["calls"] = max(0, d.get("calls", 1) - 1)
    cache["daily"] = d


# ── Public API ────────────────────────────────────────────────────────────────

def get_current_irradiance() -> dict | None:
    """
    Return current GTI and GHI (W/m²) from Solcast estimated_actuals.
    Most-recent 30-min period. Returns None when API key not set.
    """
    if not _API_KEY:
        return None

    cache = _load()
    ac = cache.get("actuals", {})

    if _age_min(ac.get("fetched_at")) < _ACTUALS_TTL_MIN:
        return ac.get("latest")

    if not _can_call(cache):
        print("Solcast: daily limit reached — serving stale cache.")
        _save(cache)
        return ac.get("latest")

    try:
        resp = requests.get(
            f"{_BASE}/estimated_actuals",
            params={
                "latitude": _LAT, "longitude": _LON,
                "hours": 2,
                "output_parameters": "ghi,gti,cloud_opacity",
                "tilt": _TILT, "azimuth": _AZIMUTH,
                "format": "json",
            },
            headers={"Authorization": f"Bearer {_API_KEY}"},
            timeout=8,
        )
        resp.raise_for_status()
        periods = resp.json().get("estimated_actuals", [])
        if periods:
            p = periods[0]  # most recent first
            latest = {
                "gti_wm2":       float(p.get("gti") or p.get("ghi") or 0),
                "ghi_wm2":       float(p.get("ghi") or 0),
                "cloud_opacity": float(p.get("cloud_opacity") or 0),
                "period_end":    p.get("period_end"),
                "source":        "solcast",
            }
            cache["actuals"] = {
                "latest":     latest,
                "fetched_at": datetime.now(timezone.utc).isoformat(),
            }
            _save(cache)
            return latest
    except Exception as e:
        print(f"Solcast actuals error: {e}")
        _rollback_call(cache)

    _save(cache)
    return ac.get("latest")  # stale cache fallback


def get_forecast() -> list[dict] | None:
    """
    Return 72-hour half-hourly forecast from Solcast.
    Each entry: {period_end, gti_wm2, ghi_wm2, cloud_opacity}
    Returns None when unavailable.
    """
    if not _API_KEY:
        return None

    cache = _load()
    fc = cache.get("forecasts", {})

    if _age_min(fc.get("fetched_at")) < _FORECAST_TTL_MIN:
        return fc.get("data")

    if not _can_call(cache):
        print("Solcast: daily limit reached — serving stale forecast.")
        _save(cache)
        return fc.get("data")

    try:
        resp = requests.get(
            f"{_BASE}/forecasts",
            params={
                "latitude": _LAT, "longitude": _LON,
                "hours": 72,
                "output_parameters": "ghi,gti,cloud_opacity",
                "tilt": _TILT, "azimuth": _AZIMUTH,
                "format": "json",
            },
            headers={"Authorization": f"Bearer {_API_KEY}"},
            timeout=10,
        )
        resp.raise_for_status()
        data = [
            {
                "period_end":    p.get("period_end"),
                "gti_wm2":       float(p.get("gti") or p.get("ghi") or 0),
                "ghi_wm2":       float(p.get("ghi") or 0),
                "cloud_opacity": float(p.get("cloud_opacity") or 0),
            }
            for p in resp.json().get("forecasts", [])
        ]
        cache["forecasts"] = {
            "data":       data,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        _save(cache)
        return data
    except Exception as e:
        print(f"Solcast forecast error: {e}")
        _rollback_call(cache)

    _save(cache)
    return fc.get("data")


def call_status() -> dict:
    """Today's API call count — exposed via /api/calibrate/status."""
    cache = _load()
    d = cache.get("daily", {})
    today = date.today().isoformat()
    if d.get("date") != today:
        return {"date": today, "calls_used": 0, "calls_remaining": _MAX_CALLS_PER_DAY, "limit": _MAX_CALLS_PER_DAY}
    used = d.get("calls", 0)
    return {"date": today, "calls_used": used, "calls_remaining": _MAX_CALLS_PER_DAY - used, "limit": _MAX_CALLS_PER_DAY}
