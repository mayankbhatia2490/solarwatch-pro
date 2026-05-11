"""
backfill.py — One-time historical data backfill from ShineMonitor to InfluxDB.

Usage (from inside the container):
    python backfill.py --start-date 2025-04-17 --end-date 2026-05-09

Or via docker compose (run from your NAS, no need to enter the container):
    sudo docker compose run --rm solar-collector python backfill.py \
        --start-date 2025-04-17 --end-date 2026-05-09

Notes:
  - Reuses all .env variables — no new credentials needed.
  - Skips days that already have data in InfluxDB.
  - Handles ShineMonitor API pagination automatically.
  - Adds a small delay between requests to avoid rate-limiting.
  - Timestamps are written in UTC (converted from IST/Asia/Kolkata).
"""

import os
import sys
import time
import hashlib
import urllib.parse
import argparse
import logging
from datetime import datetime, timedelta, timezone

import requests
from influxdb_client import InfluxDBClient, Point, WritePrecision
from influxdb_client.client.write_api import SYNCHRONOUS

# ─── Logging ─────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("backfill")

# ─── Config from environment (same .env as solar_collector) ──────────────────
USERNAME     = os.environ["SHINEMONITOR_USERNAME"]
PASSWORD     = os.environ["SHINEMONITOR_PASSWORD"]
COMPANY_KEY  = os.environ["SHINEMONITOR_COMPANY_KEY"]
PLANT_ID     = os.environ["SHINEMONITOR_PLANT_ID"]
PN           = os.environ["SHINEMONITOR_PN"]
SN           = os.environ["SHINEMONITOR_SN"]
DEVCODE      = os.environ["SHINEMONITOR_DEVCODE"]

INFLUX_URL    = os.environ.get("INFLUXDB_URL",    "http://influxdb:8086")
INFLUX_TOKEN  = os.environ["INFLUXDB_TOKEN"]
INFLUX_ORG    = os.environ.get("INFLUXDB_ORG",    "solar")
INFLUX_BUCKET = os.environ.get("INFLUXDB_BUCKET", "solar_metrics")

# IST is UTC+5:30
IST_OFFSET = timezone(timedelta(hours=5, minutes=30))

BASE_URL = "http://api.shinemonitor.com/public/"

# Fields we care about (title → influx field name)
FIELD_MAP = {
    "Output Power":                  "power_now_w",
    "Energy today":                  "daily_energy_kwh",
    "energy_total":                  "total_energy_kwh",
    "PV1 voltage":                   "pv1_voltage",
    "PV1 current":                   "pv1_current",
    "PV2 voltage":                   "pv2_voltage",
    "PV2 current":                   "pv2_current",
    "Grid R voltage":                "grid_r_voltage",
    "Grid R current":                "grid_r_current",
    "Grid S voltage":                "grid_s_voltage",
    "Grid S current":                "grid_s_current",
    "Grid T voltage":                "grid_t_voltage",
    "Grid T current":                "grid_t_current",
    "Grid frequency":                "grid_frequency",
    "bus voltage":                   "bus_voltage",
    "Internal ambient temperature":  "internal_ambient_temperature",
    "Internal radiator temperature": "internal_radiator_temperature",
    "PR":                            "performance_ratio_pct",
    "CUF":                           "capacity_utilisation_pct",
}

# ─── ShineMonitor Auth ────────────────────────────────────────────────────────

_token_cache = {}

def _salt():
    return int(round(time.time() * 1000))

def get_token():
    """Fetch a fresh auth token. Cached for the session lifetime."""
    if _token_cache.get("expires_at") and time.time() < _token_cache["expires_at"]:
        return _token_cache["token"], _token_cache["secret"]

    log.info("Authenticating with ShineMonitor...")
    salt = _salt()
    pwd_sha1 = hashlib.sha1(PASSWORD.encode()).hexdigest()
    action = f"&action=auth&usr={urllib.parse.quote(USERNAME)}&company-key={COMPANY_KEY}"
    sign = hashlib.sha1((str(salt) + pwd_sha1 + action).encode()).hexdigest()
    url = f"{BASE_URL}?sign={sign}&salt={salt}{action}"

    r = requests.get(url, timeout=15)
    data = r.json()
    if data["err"] != 0:
        log.error(f"Auth failed: {data}")
        sys.exit(1)

    dat = data["dat"]
    _token_cache["token"]      = dat["token"]
    _token_cache["secret"]     = dat["secret"]
    _token_cache["expires_at"] = time.time() + dat["expire"] - 300  # refresh 5 min early
    log.info("Auth OK.")
    return dat["token"], dat["secret"]

def signed_url(action_str):
    """Build a signed request URL using current token."""
    token, secret = get_token()
    salt = _salt()
    sign = hashlib.sha1((str(salt) + secret + token + action_str).encode()).hexdigest()
    return f"{BASE_URL}?sign={sign}&salt={salt}&token={token}{action_str}"

# ─── InfluxDB ─────────────────────────────────────────────────────────────────

def get_influx_client():
    client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
    return client, client.write_api(write_options=SYNCHRONOUS), client.query_api()

def date_has_data(query_api, date_str):
    """Return True if InfluxDB already has data points for this date (IST)."""
    # date_str = "YYYY-MM-DD" in IST; convert to UTC range
    day_start_ist = datetime.strptime(date_str, "%Y-%m-%d").replace(tzinfo=IST_OFFSET)
    day_end_ist   = day_start_ist + timedelta(days=1)

    flux = f"""
from(bucket: "{INFLUX_BUCKET}")
  |> range(start: {day_start_ist.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")},
           stop:  {day_end_ist.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
  |> filter(fn: (r) => r["_measurement"] == "solar_metrics")
  |> filter(fn: (r) => r["_field"] == "power_now_w")
  |> count()
"""
    try:
        tables = query_api.query(flux)
        for table in tables:
            for record in table.records:
                if record.get_value() and record.get_value() > 0:
                    return True
    except Exception as e:
        log.warning(f"Could not check existing data for {date_str}: {e}")
    return False

# ─── ShineMonitor Data Fetch ──────────────────────────────────────────────────

def fetch_day(date_str):
    """
    Fetch all data rows for a given date from ShineMonitor.
    Handles pagination automatically.
    Returns list of dicts: {timestamp_utc, field_name: value, ...}
    """
    all_points = []
    page = 0

    while True:
        action = (
            f"&action=queryDeviceDataOneDayPaging"
            f"&devaddr=1&pn={PN}&devcode={DEVCODE}&sn={SN}"
            f"&date={date_str}&page={page}&pagesize=100"
        )
        try:
            r = requests.get(signed_url(action), timeout=20)
            data = r.json()
        except Exception as e:
            log.error(f"  API error on {date_str} page {page}: {e}")
            break

        if data.get("err") != 0:
            log.warning(f"  API returned err={data.get('err')} for {date_str}: {data.get('desc')}")
            break

        dat = data.get("dat", {})
        titles = dat.get("title", [])
        rows   = dat.get("row",   [])

        if not rows:
            break  # No more pages

        # Build title->index mapping once per page (titles are stable across pages)
        title_index = {}
        for i, t in enumerate(titles):
            title_index[t["title"]] = i

        ts_idx = title_index.get("Timestamp")

        for row in rows:
            fields = row.get("field", [])
            if ts_idx is None or ts_idx >= len(fields):
                continue

            # Parse timestamp from IST, convert to UTC
            ts_str = fields[ts_idx]  # e.g. "2025-06-15 10:35:00"
            try:
                ts_ist = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S").replace(tzinfo=IST_OFFSET)
                ts_utc = ts_ist.astimezone(timezone.utc)
            except ValueError:
                continue

            point_data = {"timestamp_utc": ts_utc}

            for title, influx_name in FIELD_MAP.items():
                idx = title_index.get(title)
                if idx is not None and idx < len(fields):
                    try:
                        point_data[influx_name] = float(fields[idx])
                    except (ValueError, TypeError):
                        pass  # skip non-numeric like "Normal"

            all_points.append(point_data)

        # Check if there are more pages
        total     = dat.get("total", 0)
        pagesize  = dat.get("pagesize", 100)
        fetched   = (page + 1) * pagesize
        if fetched >= total:
            break
        page += 1
        time.sleep(0.3)  # be polite to the API between pages

    return all_points

# ─── Write to InfluxDB ────────────────────────────────────────────────────────

def write_points(write_api, points, date_str):
    """Write a list of data-point dicts to InfluxDB."""
    influx_points = []
    for p in points:
        pt = Point("solar_metrics").time(p["timestamp_utc"], WritePrecision.S)
        has_field = False
        for k, v in p.items():
            if k == "timestamp_utc":
                continue
            pt = pt.field(k, v)
            has_field = True
        if has_field:
            influx_points.append(pt)

    if influx_points:
        write_api.write(bucket=INFLUX_BUCKET, record=influx_points)
        log.info(f"  ✅ {date_str} — wrote {len(influx_points)} points to InfluxDB")
    else:
        log.info(f"  ⚠️  {date_str} — no usable data points returned by API")

# ─── Main ─────────────────────────────────────────────────────────────────────

def date_range(start: datetime, end: datetime):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)

def main():
    parser = argparse.ArgumentParser(description="Backfill ShineMonitor historical data into InfluxDB")
    parser.add_argument("--start-date", required=True, help="Start date YYYY-MM-DD (e.g. 2025-04-17)")
    parser.add_argument("--end-date",   required=True, help="End date   YYYY-MM-DD (e.g. 2026-05-09)")
    parser.add_argument("--force",      action="store_true",
                        help="Re-write even if data already exists for that day")
    args = parser.parse_args()

    try:
        start = datetime.strptime(args.start_date, "%Y-%m-%d")
        end   = datetime.strptime(args.end_date,   "%Y-%m-%d")
    except ValueError:
        log.error("Invalid date format. Use YYYY-MM-DD.")
        sys.exit(1)

    if start > end:
        log.error("--start-date must be before --end-date.")
        sys.exit(1)

    total_days = (end - start).days + 1
    log.info(f"Backfill: {args.start_date} → {args.end_date} ({total_days} days)")
    log.info(f"InfluxDB: {INFLUX_URL} / org={INFLUX_ORG} / bucket={INFLUX_BUCKET}")

    client, write_api, query_api = get_influx_client()

    skipped  = 0
    written  = 0
    no_data  = 0
    errors   = 0

    for i, day in enumerate(date_range(start, end), 1):
        date_str = day.strftime("%Y-%m-%d")
        log.info(f"[{i}/{total_days}] Processing {date_str}...")

        # Skip if already populated (unless --force)
        if not args.force and date_has_data(query_api, date_str):
            log.info(f"  ⏭  {date_str} — already has data, skipping")
            skipped += 1
            continue

        try:
            points = fetch_day(date_str)
            if points:
                write_points(write_api, points, date_str)
                written += 1
            else:
                log.info(f"  ⚠️  {date_str} — no data from API (inverter may have been offline)")
                no_data += 1
        except Exception as e:
            log.error(f"  ❌ {date_str} — error: {e}")
            errors += 1

        # Polite delay between days to avoid API rate-limiting
        time.sleep(1.0)

    client.close()

    log.info("=" * 50)
    log.info(f"Backfill complete!")
    log.info(f"  Written:  {written} days")
    log.info(f"  Skipped:  {skipped} days (already had data)")
    log.info(f"  No data:  {no_data} days (inverter offline / no readings)")
    log.info(f"  Errors:   {errors} days")
    log.info("=" * 50)


if __name__ == "__main__":
    main()
