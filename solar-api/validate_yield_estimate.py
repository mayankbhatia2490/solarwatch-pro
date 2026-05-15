"""
Validates the annual yield estimate (tilt-analysis.html) against:
  1. NASA POWER / Open-Meteo Archive actual GHI for Karnal
  2. Your real InfluxDB generation data since installation

Run:
  python3 validate_yield_estimate.py

Outputs a comparison table: model estimate vs actual for each available month.
"""
import os, sys, requests
from datetime import datetime, date, timezone, timedelta
from collections import defaultdict
from influxdb_client import InfluxDBClient

# ── Config ────────────────────────────────────────────────────────────────────
INFLUX_URL    = os.environ.get("INFLUXDB_URL",    "http://localhost:8086")
INFLUX_TOKEN  = os.environ.get("INFLUXDB_TOKEN",  "")
INFLUX_ORG    = os.environ.get("INFLUXDB_ORG",    "solar")
INFLUX_BUCKET = os.environ.get("INFLUXDB_BUCKET", "solar_metrics")
LATITUDE      = float(os.environ.get("LATITUDE",  "29.693405600010355"))
LONGITUDE     = float(os.environ.get("LONGITUDE", "76.99938211551195"))
TIMEZONE      = os.environ.get("TIMEZONE", "Asia/Kolkata")
INSTALL_DATE  = "2025-04-17"

CAPACITY_W         = float(os.environ.get("INSTALLED_CAPACITY_W", "3570"))
TEMP_COEFF         = -0.0030
NOCT               = 45.0
BIFACIAL_REAR_GAIN = 0.09
SYSTEM_PR          = float(os.environ.get("SYSTEM_PR", "0.83"))
PANEL_TILT         = 5
PANEL_AZIMUTH      = 0

# ── My original tilt-analysis.html estimate (GHI-based, climate averages) ────
# Monthly GHI (kWh/m²/day) used in the HTML tool
MODEL_GHI = {
    1: 3.6, 2: 4.4, 3: 5.6,  4: 6.5,  5: 7.0,  6: 6.2,
    7: 4.8, 8: 4.5, 9: 5.2, 10: 5.5, 11: 4.2, 12: 3.4
}
# Tilt correction factors used in the HTML tool (5° south-facing, 29.7°N)
MODEL_TILT_FACTOR = {
    1: 1.10, 2: 1.07, 3: 1.02, 4: 0.98, 5: 0.96, 6: 0.95,
    7: 0.96, 8: 0.98, 9: 1.01, 10: 1.06, 11: 1.09, 12: 1.11
}
DAYS_IN_MONTH = {1:31,2:28,3:31,4:30,5:31,6:30,7:31,8:31,9:30,10:31,11:30,12:31}


# ── Helpers ───────────────────────────────────────────────────────────────────

def compute_expected(poa_wm2: float, temp_c: float) -> float:
    T_cell = temp_c + (NOCT - 20.0) * (poa_wm2 / 800.0)
    corr   = 1 + TEMP_COEFF * (T_cell - 25.0)
    return max(0.0, (poa_wm2 / 1000.0) * CAPACITY_W * (1 + BIFACIAL_REAR_GAIN) * SYSTEM_PR * corr)


def fetch_archive_hourly(start: str, end: str) -> dict:
    """Fetch actual hourly GHI + POA + temperature from Open-Meteo Archive."""
    print(f"  Fetching Open-Meteo Archive ({start} → {end}) ...")
    url = (
        f"https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={LATITUDE}&longitude={LONGITUDE}"
        f"&start_date={start}&end_date={end}"
        f"&hourly=shortwave_radiation,global_tilted_irradiance,temperature_2m"
        f"&tilt={PANEL_TILT}&azimuth={PANEL_AZIMUTH}"
        f"&timezone={TIMEZONE}"
    )
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    h      = r.json().get("hourly", {})
    times  = h.get("time", [])
    ghi_h  = h.get("shortwave_radiation", [])
    poa_h  = h.get("global_tilted_irradiance", [])
    temp_h = h.get("temperature_2m", [])

    # Aggregate to daily totals and daily averages
    daily_ghi  = defaultdict(float)
    daily_poa  = defaultdict(float)
    daily_temp = defaultdict(list)

    for i, t in enumerate(times):
        d = t[:10]
        daily_ghi[d]  += (ghi_h[i]  or 0) / 1000.0   # W/m² → kWh/m² per hour
        daily_poa[d]  += (poa_h[i]  or 0) / 1000.0
        daily_temp[d].append(temp_h[i] or 30.0)

    result = {}
    for d in daily_ghi:
        avg_temp = sum(daily_temp[d]) / len(daily_temp[d]) if daily_temp[d] else 30.0
        result[d] = {
            "ghi_kwh_m2":  round(daily_ghi[d], 2),
            "poa_kwh_m2":  round(daily_poa[d], 2),
            "avg_temp_c":  round(avg_temp, 1),
        }
    return result


def fetch_actual_daily_kwh(client: InfluxDBClient) -> dict:
    """Query InfluxDB for actual daily energy generation (kWh per day)."""
    print("  Querying InfluxDB for actual daily generation ...")
    flux = f'''
from(bucket: "{INFLUX_BUCKET}")
  |> range(start: {INSTALL_DATE}T00:00:00Z)
  |> filter(fn: (r) => r["_field"] == "daily_energy_kwh")
  |> aggregateWindow(every: 1d, fn: max, createEmpty: false)
  |> keep(columns: ["_time", "_value"])
'''
    tables = client.query_api().query(flux, org=INFLUX_ORG)
    result = {}
    for table in tables:
        for record in table.records:
            d = record.get_time().strftime("%Y-%m-%d")
            result[d] = round(float(record.get_value() or 0), 2)
    return result


# ── Main validation ───────────────────────────────────────────────────────────

def run():
    today_str = date.today().isoformat()
    print("\n" + "="*70)
    print("  YIELD ESTIMATE VALIDATION — Karnal 29.7°N, 3.57kWp, 5° south")
    print("="*70)

    # 1. Fetch actual weather from Open-Meteo Archive
    print("\n[1] Fetching actual historical weather data ...")
    try:
        archive = fetch_archive_hourly(INSTALL_DATE, today_str)
    except Exception as e:
        print(f"  ERROR fetching archive: {e}")
        sys.exit(1)

    # 2. Fetch actual generation from InfluxDB
    print("\n[2] Fetching actual generation from InfluxDB ...")
    try:
        client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
        actual_daily = fetch_actual_daily_kwh(client)
        client.close()
    except Exception as e:
        print(f"  ERROR querying InfluxDB: {e}")
        actual_daily = {}

    # 3. Compute model prediction using ACTUAL archive weather (not climate averages)
    print("\n[3] Computing model prediction from actual archive weather ...")
    model_actual_weather = {}   # prediction using real weather data
    for d, w in archive.items():
        # Use hourly POA to estimate daily expected kWh
        # We have daily total POA (kWh/m²), convert back to average hourly W/m²
        # to run through the temp-corrected formula
        avg_poa_wm2 = w["poa_kwh_m2"] * 1000 / 24.0  # rough hourly average
        kwh = compute_expected(avg_poa_wm2, w["avg_temp_c"]) * 24 / 1000
        model_actual_weather[d] = round(kwh, 2)

    # Better: directly use poa_kwh_m2 × system_params
    model_actual_weather2 = {}
    for d, w in archive.items():
        kwh = w["poa_kwh_m2"] * (CAPACITY_W / 1000) * (1 + BIFACIAL_REAR_GAIN) * SYSTEM_PR
        model_actual_weather2[d] = round(kwh, 2)

    # 4. Compare model estimate (climate averages) vs archive-model vs actual
    print("\n[4] Monthly comparison:\n")

    months_seen = sorted(set(d[:7] for d in archive.keys()))

    # Header
    print(f"{'Month':<10} {'Climate-est':>12} {'Archive-model':>14} {'Actual':>10} {'vs Estimate':>12} {'vs Model':>10} {'Days':>5}")
    print("-" * 78)

    total_climate  = 0
    total_archive  = 0
    total_actual   = 0
    total_days_act = 0

    for ym in months_seen:
        yr, mo = int(ym[:4]), int(ym[5:7])
        days_in_archive = [d for d in archive if d.startswith(ym)]
        days_with_actual = [d for d in days_in_archive if d in actual_daily and actual_daily[d] > 0]

        # Climate-average estimate (from tilt-analysis.html), prorated to days available
        full_days     = DAYS_IN_MONTH.get(mo, 30)
        climate_daily = MODEL_GHI[mo] * MODEL_TILT_FACTOR[mo] * (CAPACITY_W/1000) * SYSTEM_PR
        climate_kwh   = round(climate_daily * len(days_in_archive), 1)

        # Archive-model (real weather, same PR formula)
        archive_kwh = round(sum(model_actual_weather2.get(d, 0) for d in days_in_archive), 1)

        # Actual from inverter
        actual_kwh  = round(sum(actual_daily.get(d, 0) for d in days_with_actual), 1)
        n_actual    = len(days_with_actual)

        # Differences
        vs_estimate = f"{((actual_kwh/climate_kwh)-1)*100:+.1f}%" if climate_kwh > 0 and actual_kwh > 0 else "—"
        vs_model    = f"{((actual_kwh/archive_kwh)-1)*100:+.1f}%" if archive_kwh > 0 and actual_kwh > 0 else "—"

        total_climate  += climate_kwh
        total_archive  += archive_kwh
        total_actual   += actual_kwh
        total_days_act += n_actual

        print(f"{ym:<10} {climate_kwh:>10.1f}  {archive_kwh:>12.1f}  {actual_kwh:>8.1f}  {vs_estimate:>12} {vs_model:>10}  {n_actual:>4}d")

    print("-" * 78)
    vs_est_tot = f"{((total_actual/total_climate)-1)*100:+.1f}%" if total_climate > 0 and total_actual > 0 else "—"
    vs_mod_tot = f"{((total_actual/total_archive)-1)*100:+.1f}%" if total_archive > 0 and total_actual > 0 else "—"
    print(f"{'TOTAL':<10} {total_climate:>10.1f}  {total_archive:>12.1f}  {total_actual:>8.1f}  {vs_est_tot:>12} {vs_mod_tot:>10}  {total_days_act:>4}d")

    # 5. Annual projection
    if total_actual > 0 and total_days_act > 0:
        daily_avg = total_actual / total_days_act
        annual_proj = round(daily_avg * 365)
        print(f"\n[5] Annual projection from actual data:")
        print(f"  Average daily generation: {daily_avg:.2f} kWh/day")
        print(f"  Projected annual yield:   {annual_proj} kWh/year")
        print(f"  HTML estimate was:        5,566 kWh/year  (at 5° tilt, PR=0.83)")
        diff = annual_proj - 5566
        print(f"  Difference:               {diff:+d} kWh/year ({diff/5566*100:+.1f}%)")

    # 6. Validate the GHI values used in the HTML
    print(f"\n[6] GHI validation — model vs actual Open-Meteo Archive:")
    print(f"  {'Month':<10} {'Model GHI':>10} {'Archive GHI':>12} {'Diff':>8}")
    print(f"  {'-'*44}")
    for ym in months_seen:
        mo = int(ym[5:7])
        days = [d for d in archive if d.startswith(ym)]
        if not days: continue
        archive_ghi_avg = sum(archive[d]["ghi_kwh_m2"] for d in days) / len(days)
        model_ghi_avg   = MODEL_GHI[mo]
        diff_pct = (archive_ghi_avg / model_ghi_avg - 1) * 100 if model_ghi_avg > 0 else 0
        print(f"  {ym:<10} {model_ghi_avg:>8.2f}     {archive_ghi_avg:>10.2f}   {diff_pct:>+6.1f}%")

    print("\nDone.\n")


if __name__ == "__main__":
    run()
