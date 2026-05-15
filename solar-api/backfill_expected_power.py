"""
Backfill expected_power_w in InfluxDB using corrected formula:
  - POA irradiance (global_tilted_irradiance at 5°/south) from Open-Meteo Archive
  - PR = 0.83 (was 0.78)
  - Bifacial rear gain = 0.09 (was 0.07)
  - NOCT cell temp formula (was fixed +25°C)
  - Temp coefficient = -0.0030 (Vikram HyperSol N-type; was -0.0039)

Run once from the project root:
  python3 backfill_expected_power.py

Requires: influxdb-client, requests  (already installed in solar-api/collector)
"""
import os, sys, requests
from datetime import datetime, timezone, timedelta
from influxdb_client import InfluxDBClient, Point, WriteOptions
from influxdb_client.client.write_api import SYNCHRONOUS

# ── Config ────────────────────────────────────────────────────────────────────
INFLUX_URL    = os.environ.get("INFLUXDB_URL",    "http://localhost:8086")
INFLUX_TOKEN  = os.environ.get("INFLUXDB_TOKEN",  "")
INFLUX_ORG    = os.environ.get("INFLUXDB_ORG",    "solar")
INFLUX_BUCKET = os.environ.get("INFLUXDB_BUCKET", "solar_metrics")

LATITUDE  = float(os.environ.get("LATITUDE",  "29.693405600010355"))
LONGITUDE = float(os.environ.get("LONGITUDE", "76.99938211551195"))
TIMEZONE  = os.environ.get("TIMEZONE", "Asia/Kolkata")

INSTALL_DATE = "2025-04-17"   # start of data

# Panel + system constants (new correct values)
PANEL_TILT         = 5
PANEL_AZIMUTH      = 0
CAPACITY_W         = float(os.environ.get("INSTALLED_CAPACITY_W", "3570"))
TEMP_COEFF         = -0.0030
NOCT               = 45.0
BIFACIAL_REAR_GAIN = 0.09
SYSTEM_PR          = float(os.environ.get("SYSTEM_PR", "0.83"))


def compute_expected(poa_wm2: float, temp_c: float) -> float:
    T_cell = temp_c + (NOCT - 20.0) * (poa_wm2 / 800.0)
    corr   = 1 + TEMP_COEFF * (T_cell - 25.0)
    return max(0.0, round((poa_wm2 / 1000.0) * CAPACITY_W * (1 + BIFACIAL_REAR_GAIN) * SYSTEM_PR * corr, 1))


def fetch_historical_poa(start_date: str, end_date: str) -> dict:
    """Fetch hourly POA + temperature from Open-Meteo Archive API."""
    print(f"Fetching Open-Meteo Archive: {start_date} → {end_date} ...")
    url = (
        f"https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={LATITUDE}&longitude={LONGITUDE}"
        f"&start_date={start_date}&end_date={end_date}"
        f"&hourly=global_tilted_irradiance,temperature_2m"
        f"&tilt={PANEL_TILT}&azimuth={PANEL_AZIMUTH}"
        f"&timezone={TIMEZONE}"
    )
    r = requests.get(url, timeout=30)
    r.raise_for_status()
    data    = r.json()
    hourly  = data.get("hourly", {})
    times   = hourly.get("time", [])
    poa_raw = hourly.get("global_tilted_irradiance", [])
    temp_raw= hourly.get("temperature_2m", [])

    # Build lookup: "YYYY-MM-DDTHH" → (poa, temp)
    lookup = {}
    for i, t in enumerate(times):
        key  = t[:13]   # "YYYY-MM-DDTHH"
        poa  = poa_raw[i]  if i < len(poa_raw)  and poa_raw[i]  is not None else 0.0
        temp = temp_raw[i] if i < len(temp_raw) and temp_raw[i] is not None else 30.0
        lookup[key] = (float(poa), float(temp))

    print(f"  Fetched {len(lookup)} hourly records from Open-Meteo Archive.")
    return lookup


def query_influx_timestamps(client: InfluxDBClient) -> list:
    """Return list of (timestamp_rfc3339, stored_temp_c) for all data points."""
    print("Querying InfluxDB for all data point timestamps ...")
    flux = f'''
from(bucket: "{INFLUX_BUCKET}")
  |> range(start: {INSTALL_DATE}T00:00:00Z)
  |> filter(fn: (r) => r["_field"] == "temperature_c")
  |> keep(columns: ["_time", "_value"])
'''
    tables = client.query_api().query(flux, org=INFLUX_ORG)
    rows = []
    for table in tables:
        for record in table.records:
            rows.append((record.get_time(), float(record.get_value() or 30.0)))
    print(f"  Found {len(rows)} data points in InfluxDB.")
    return rows


def backfill(dry_run: bool = False):
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # 1. Fetch historical POA from Open-Meteo Archive
    poa_lookup = fetch_historical_poa(INSTALL_DATE, today)
    if not poa_lookup:
        print("ERROR: No data from Open-Meteo Archive. Aborting.")
        sys.exit(1)

    # 2. Connect to InfluxDB
    client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
    rows   = query_influx_timestamps(client)
    if not rows:
        print("No data found in InfluxDB. Nothing to backfill.")
        return

    # 3. Compute corrected expected_power_w for each data point
    points     = []
    unchanged  = 0
    updated    = 0
    for ts, stored_temp in rows:
        hour_key = ts.strftime("%Y-%m-%dT%H")
        if hour_key in poa_lookup:
            poa, temp = poa_lookup[hour_key]
            # Use Open-Meteo temperature if stored is 0 (fallback)
            use_temp = stored_temp if stored_temp > 0 else temp
        else:
            # No Archive data for this hour — skip (rare edge case)
            unchanged += 1
            continue

        new_expected = compute_expected(poa, use_temp)
        updated += 1

        if not dry_run:
            p = (
                Point("solar_reading")
                .tag("site_id", os.environ.get("SITE_ID", "default"))
                .time(ts)
                .field("expected_power_w",   new_expected)
                .field("poa_irradiance_wm2", poa)
            )
            points.append(p)

    print(f"  {updated} points to update, {unchanged} skipped (no Archive data).")

    if dry_run:
        print("DRY RUN — no writes performed.")
        return

    # 4. Write in batches of 5000
    write_api = client.write_api(write_options=SYNCHRONOUS)
    batch_size = 5000
    for i in range(0, len(points), batch_size):
        batch = points[i:i + batch_size]
        write_api.write(bucket=INFLUX_BUCKET, record=batch)
        print(f"  Written {min(i + batch_size, len(points))} / {len(points)} points ...")

    client.close()
    print(f"Backfill complete. {updated} expected_power_w values corrected.")


if __name__ == "__main__":
    dry = "--dry-run" in sys.argv
    if dry:
        print("=== DRY RUN MODE — no data will be written ===")
    backfill(dry_run=dry)
