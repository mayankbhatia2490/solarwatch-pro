"""
Irradiance Source Calibration
==============================
Compares PVGIS-SARAH3, Open-Meteo Archive, and VEDAS ISRO monthly GHI against
actual InfluxDB solar production to find which source is most accurate for Karnal.

Writes result to /app/irradiance_cal.json so weather.py applies the
correction factor automatically.  Runs once on API startup (background
task) and can be re-triggered via POST /api/calibrate/run.

Usage (manual, inside container):
    python3 calibrate_irradiance.py
"""
import os, sys, json, requests
from datetime import datetime, date, timezone, timedelta
from calendar import monthrange

# ── Config ────────────────────────────────────────────────────────────────────
INFLUX_URL    = os.environ.get("INFLUXDB_URL",    "http://influxdb:8086")
INFLUX_TOKEN  = os.environ.get("INFLUXDB_TOKEN",  "")
INFLUX_ORG    = os.environ.get("INFLUXDB_ORG",    "solar")
INFLUX_BUCKET = os.environ.get("INFLUXDB_BUCKET", "solar_metrics")
LATITUDE      = float(os.environ.get("LATITUDE",   "29.693388853916030"))
LONGITUDE     = float(os.environ.get("LONGITUDE",  "76.999477683624900"))
CAL_FILE      = os.environ.get("CAL_FILE",         "/app/irradiance_cal.json")

CAPACITY_KWP = 3.57
BIFACIAL     = 1.09
PR           = 0.83

# Tilt correction factors (POA/GHI) for 5.2° south-facing at 29.7°N
# Liu-Jordan model, months Jan-Dec
TILT_FACTORS = [1.10, 1.07, 1.02, 0.98, 0.96, 0.95, 0.96, 0.98, 1.01, 1.06, 1.09, 1.11]

# VEDAS ISRO long-term monthly GHI for Karnal, Haryana (kWh/m²/day)
# Source: vedas.sac.gov.in — validated against user-provided charts (2024-2025 actual data)
VEDAS_GHI = {
    1: 2.00, 2: 2.96, 3: 4.29, 4: 5.57, 5: 4.90, 6: 4.70,
    7: 3.45, 8: 4.00, 9: 4.37, 10: 3.13, 11: 2.23, 12: 1.90,
}

# ── Helpers ───────────────────────────────────────────────────────────────────

def month_to_kwh(ghi_daily: float, month: int, year: int) -> float:
    """Convert daily GHI (kWh/m²/day) → expected system output (kWh)."""
    days = monthrange(year, month)[1]
    tf   = TILT_FACTORS[month - 1]
    return ghi_daily * days * CAPACITY_KWP * BIFACIAL * PR * tf


def query_influx(flux: str) -> list:
    url = f"{INFLUX_URL}/api/v2/query?org={INFLUX_ORG}"
    headers = {"Authorization": f"Token {INFLUX_TOKEN}", "Content-Type": "application/vnd.flux"}
    r = requests.post(url, headers=headers, data=flux, timeout=30)
    r.raise_for_status()
    rows = []
    for line in r.text.splitlines():
        if line.startswith("#") or not line.strip() or line.startswith(",result"):
            continue
        rows.append(line.split(","))
    return rows


def actual_monthly_kwh(year: int, month: int) -> float | None:
    """Return total kWh generated in given month from InfluxDB."""
    start = f"{year}-{month:02d}-01T00:00:00Z"
    days  = monthrange(year, month)[1]
    end   = f"{year}-{month:02d}-{days:02d}T23:59:59Z"
    flux  = f'''
from(bucket: "{INFLUX_BUCKET}")
  |> range(start: {start}, stop: {end})
  |> filter(fn: (r) => r["_measurement"] == "solar_metrics" and r["_field"] == "energy_wh")
  |> sum()
'''
    try:
        rows = query_influx(flux)
        for row in rows:
            if len(row) >= 7:
                try:
                    return float(row[6]) / 1000.0  # Wh → kWh
                except (ValueError, IndexError):
                    pass
    except Exception as e:
        print(f"  InfluxDB query failed for {year}-{month:02d}: {e}")
    return None


# ── PVGIS ─────────────────────────────────────────────────────────────────────

def fetch_pvgis_monthly() -> dict[int, float]:
    """
    Fetch long-term monthly GHI averages from PVGIS SARAH-3.
    Returns {month: ghi_kWh_per_m2_per_day}
    """
    url = "https://re.jrc.ec.europa.eu/api/v5_2/MRcalc"
    params = {
        "lat":          LATITUDE,
        "lon":          LONGITUDE,
        "raddatabase":  "PVGIS-SARAH3",
        "outputformat": "json",
        "startyear":    2010,
        "endyear":      2020,
    }
    print("  Fetching PVGIS-SARAH3 monthly GHI…")
    r = requests.get(url, params=params, timeout=30)
    r.raise_for_status()
    data = r.json()

    monthly = {}
    for entry in data.get("outputs", {}).get("monthly", {}).get("fixed", []):
        m   = entry["month"]                   # 1-12
        ghi = entry.get("G(h)", 0) / 30.44    # kWh/m²/month → approx daily
        monthly[m] = ghi
    return monthly


# ── Open-Meteo Archive ────────────────────────────────────────────────────────

def fetch_openmeteo_monthly(year: int, month: int) -> float | None:
    """
    Fetch daily shortwave_radiation_sum for a specific month from Open-Meteo Archive.
    Returns monthly average GHI (kWh/m²/day).
    """
    days      = monthrange(year, month)[1]
    start_str = f"{year}-{month:02d}-01"
    end_str   = f"{year}-{month:02d}-{days:02d}"
    url = (
        f"https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={LATITUDE}&longitude={LONGITUDE}"
        f"&start_date={start_str}&end_date={end_str}"
        f"&daily=shortwave_radiation_sum"
        f"&timezone=Asia%2FKolkata"
    )
    try:
        r = requests.get(url, timeout=20)
        r.raise_for_status()
        vals = r.json().get("daily", {}).get("shortwave_radiation_sum", [])
        valid = [v for v in vals if v is not None]
        if not valid:
            return None
        total_mj = sum(valid)          # MJ/m² per day values summed over month
        # Open-Meteo shortwave_radiation_sum is in MJ/m², convert to kWh/m²
        total_kwh = total_mj / 3.6
        return total_kwh / len(valid)  # daily average kWh/m²/day
    except Exception as e:
        print(f"    Open-Meteo archive failed for {year}-{month:02d}: {e}")
        return None


# ── VEDAS ISRO ────────────────────────────────────────────────────────────────

def get_vedas_monthly(month: int) -> float | None:
    """
    Return VEDAS ISRO long-term monthly GHI average for Karnal (kWh/m²/day).
    VEDAS does not expose a simple public REST API, so we use validated
    long-term averages from vedas.sac.gov.in for this location.
    """
    return VEDAS_GHI.get(month)


# ── Main calibration ──────────────────────────────────────────────────────────

def run_calibration() -> dict:
    print("\n=== Irradiance Source Calibration (PVGIS vs Open-Meteo vs VEDAS ISRO) ===")
    print(f"Location: {LATITUDE}°N, {LONGITUDE}°E  |  Capacity: {CAPACITY_KWP} kWp\n")

    # 1. Determine months to compare (last 12 months with actual data)
    today  = date.today()
    months = []
    for i in range(13, 0, -1):
        d = date(today.year, today.month, 1) - timedelta(days=i * 28)
        months.append((d.year, d.month))
    months = months[-12:]  # keep most recent 12

    # 2. Fetch PVGIS long-term monthly averages
    try:
        pvgis_avg = fetch_pvgis_monthly()
    except Exception as e:
        print(f"  PVGIS fetch failed: {e}")
        pvgis_avg = {}

    # 3. Compare month by month
    results = []
    pvgis_errors, om_errors, vedas_errors = [], [], []

    print(f"{'Month':<10} {'Actual kWh':>11} {'PVGIS exp':>10} {'OM exp':>10} {'VEDAS exp':>10} {'PVGIS err%':>11} {'OM err%':>8} {'VEDAS err%':>11}")
    print("-" * 90)

    for year, month in months:
        actual = actual_monthly_kwh(year, month)
        if actual is None or actual < 10:
            print(f"{year}-{month:02d}   {'(no data)':>11}")
            continue

        # PVGIS expected
        pvgis_ghi = pvgis_avg.get(month)
        pvgis_exp = month_to_kwh(pvgis_ghi, month, year) if pvgis_ghi else None

        # Open-Meteo Archive expected
        om_ghi = fetch_openmeteo_monthly(year, month)
        om_exp = month_to_kwh(om_ghi, month, year) if om_ghi else None

        # VEDAS ISRO expected (long-term monthly averages)
        vedas_ghi = get_vedas_monthly(month)
        vedas_exp = month_to_kwh(vedas_ghi, month, year) if vedas_ghi else None

        pvgis_err = abs(pvgis_exp - actual) / actual * 100 if pvgis_exp else None
        om_err    = abs(om_exp   - actual) / actual * 100 if om_exp   else None
        vedas_err = abs(vedas_exp - actual) / actual * 100 if vedas_exp else None

        if pvgis_err  is not None: pvgis_errors.append(pvgis_err)
        if om_err     is not None: om_errors.append(om_err)
        if vedas_err  is not None: vedas_errors.append(vedas_err)

        results.append({
            "year": year, "month": month,
            "actual_kwh":  round(actual, 1),
            "pvgis_exp":   round(pvgis_exp, 1)  if pvgis_exp  else None,
            "om_exp":      round(om_exp, 1)      if om_exp     else None,
            "vedas_exp":   round(vedas_exp, 1)   if vedas_exp  else None,
            "pvgis_err":   round(pvgis_err, 1)   if pvgis_err  else None,
            "om_err":      round(om_err, 1)       if om_err     else None,
            "vedas_err":   round(vedas_err, 1)    if vedas_err  else None,
        })

        print(
            f"{year}-{month:02d}   "
            f"{actual:>10.1f}  "
            f"{pvgis_exp or 0:>9.1f}  "
            f"{om_exp or 0:>9.1f}  "
            f"{vedas_exp or 0:>9.1f}  "
            f"{pvgis_err or 0:>10.1f}%  "
            f"{om_err or 0:>7.1f}%  "
            f"{vedas_err or 0:>10.1f}%"
        )

    if not pvgis_errors and not om_errors and not vedas_errors:
        print("\nNo comparison data available — keeping Open-Meteo as default.")
        return {"winner": "openmeteo", "reason": "no_data"}

    pvgis_mape = sum(pvgis_errors) / len(pvgis_errors) if pvgis_errors else 999
    om_mape    = sum(om_errors)    / len(om_errors)    if om_errors    else 999
    vedas_mape = sum(vedas_errors) / len(vedas_errors) if vedas_errors else 999

    print(f"\nPVGIS   MAPE: {pvgis_mape:.1f}%  ({len(pvgis_errors)} months)")
    print(f"OpenMet MAPE: {om_mape:.1f}%  ({len(om_errors)} months)")
    print(f"VEDAS   MAPE: {vedas_mape:.1f}%  ({len(vedas_errors)} months)")

    # 4. Pick winner (lowest MAPE)
    scores = {"pvgis": pvgis_mape, "openmeteo": om_mape, "vedas": vedas_mape}
    winner = min(scores, key=scores.get)

    # 5. Compute monthly correction factors for the winner
    # correction_factor[month] = actual / source_expected (clipped to 0.5–1.5)
    correction = {}
    for r in results:
        if winner == "pvgis" and r["pvgis_exp"] and r["actual_kwh"]:
            raw = r["actual_kwh"] / r["pvgis_exp"]
            correction[r["month"]] = round(min(1.5, max(0.5, raw)), 4)
        elif winner == "openmeteo" and r["om_exp"] and r["actual_kwh"]:
            raw = r["actual_kwh"] / r["om_exp"]
            correction[r["month"]] = round(min(1.5, max(0.5, raw)), 4)
        elif winner == "vedas" and r["vedas_exp"] and r["actual_kwh"]:
            raw = r["actual_kwh"] / r["vedas_exp"]
            correction[r["month"]] = round(min(1.5, max(0.5, raw)), 4)

    # Fill any missing months with 1.0
    for m in range(1, 13):
        correction.setdefault(m, 1.0)

    cal = {
        "winner":             winner,
        "pvgis_mape":         round(pvgis_mape, 2),
        "openmeteo_mape":     round(om_mape, 2),
        "vedas_mape":         round(vedas_mape, 2),
        "months_compared":    len(results),
        "correction_factors": {int(k): v for k, v in correction.items()},
        "calibrated_at":      datetime.now(timezone.utc).isoformat(),
        "monthly_detail":     results,
    }

    print(f"\n✓ Winner: {winner.upper()}  (lowest MAPE = most accurate for Karnal)")
    print(f"  Monthly correction factors: {correction}")

    try:
        with open(CAL_FILE, "w") as f:
            json.dump(cal, f, indent=2)
        print(f"  Saved to {CAL_FILE}")
    except Exception as e:
        print(f"  Warning: could not save {CAL_FILE}: {e}")

    return cal


if __name__ == "__main__":
    cal = run_calibration()
    sys.exit(0)
