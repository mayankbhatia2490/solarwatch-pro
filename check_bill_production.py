"""
Bill production comparison — run this on the NAS:

  docker exec solar-api python /app/check_bill_production.py

Compares InfluxDB daily_energy_kwh totals for the billing period
against the UHBVN meter reading from the bill.
"""
import sys
import os

# Allow running from repo root by adding solar-api to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "solar-api"))

from influxdb_client import InfluxDBClient
from config import settings

# ── Bill values to verify against ─────────────────────────────────────────────
BILL_START      = "2026-04-14T00:00:00+05:30"
BILL_END        = "2026-05-14T23:59:59+05:30"
BILL_SOLAR_KWH  = 437.0   # KWHS meter: 4334 − 3897 (solar meter reading)
BILL_IMPORT_KWH = 442.0   # KWHI: grid import
BILL_EXPORT_KWH = 192.0   # KWHE: export to grid

BUCKET = settings.influxdb_bucket

flux_daily = f'''
from(bucket: "{BUCKET}")
  |> range(start: {BILL_START}, stop: {BILL_END})
  |> filter(fn: (r) => r["_field"] == "daily_energy_kwh")
  |> filter(fn: (r) => r["_value"] > 0)
  |> sort(columns: ["_time"])
'''

flux_export = f'''
from(bucket: "{BUCKET}")
  |> range(start: {BILL_START}, stop: {BILL_END})
  |> filter(fn: (r) => r["_field"] == "energy_exported_kwh")
  |> filter(fn: (r) => r["_value"] > 0)
  |> sort(columns: ["_time"])
'''

flux_import = f'''
from(bucket: "{BUCKET}")
  |> range(start: {BILL_START}, stop: {BILL_END})
  |> filter(fn: (r) => r["_field"] == "energy_imported_kwh")
  |> filter(fn: (r) => r["_value"] > 0)
  |> sort(columns: ["_time"])
'''

client = InfluxDBClient(
    url=settings.influxdb_url,
    token=settings.influxdb_token,
    org=settings.influxdb_org,
)
qapi = client.query_api()

def run_query(flux):
    try:
        tables = qapi.query(flux, org=settings.influxdb_org)
        return [r for table in tables for r in table.records]
    except Exception as e:
        print(f"  Query error: {e}")
        return []

print("=" * 60)
print("UHBVN Bill vs App Data Comparison")
print(f"Bill period : 14/04/2026 – 14/05/2026 (30 days)")
print("=" * 60)

# ── Solar generation ──────────────────────────────────────────────────────────
print("\n▶ Solar Generation (daily_energy_kwh)")
recs = run_query(flux_daily)
daily_rows = {}
for r in recs:
    from datetime import timedelta
    ist = r.get_time() + timedelta(hours=5, minutes=30)
    date_str = ist.strftime("%Y-%m-%d")
    val = float(r.get_value() or 0)
    # keep highest value per day (end-of-day reading)
    if date_str not in daily_rows or val > daily_rows[date_str]:
        daily_rows[date_str] = val

if daily_rows:
    for d in sorted(daily_rows):
        print(f"  {d}  {daily_rows[d]:6.2f} kWh")
    app_total = sum(daily_rows.values())
    diff      = app_total - BILL_SOLAR_KWH
    pct       = diff / BILL_SOLAR_KWH * 100
    print(f"\n  App total   : {app_total:.2f} kWh ({len(daily_rows)} days with data)")
    print(f"  Bill (KWHS) : {BILL_SOLAR_KWH:.2f} kWh")
    print(f"  Difference  : {diff:+.2f} kWh ({pct:+.1f}%)")
    if abs(pct) < 3:
        print("  ✅ Match within 3% — data is consistent")
    elif abs(pct) < 10:
        print("  ⚠️  Within 10% — minor discrepancy (rounding, timing)")
    else:
        print("  ❌ Large gap — check for missing days in InfluxDB")
else:
    print("  ❌ No daily_energy_kwh records found for this period")
    print("     (collector may have been offline, or field name differs)")

# ── Export ────────────────────────────────────────────────────────────────────
print(f"\n▶ Export to Grid (energy_exported_kwh)")
exp_recs = run_query(flux_export)
if exp_recs:
    app_exp = sum(float(r.get_value() or 0) for r in exp_recs)
    diff = app_exp - BILL_EXPORT_KWH
    print(f"  App total   : {app_exp:.2f} kWh")
    print(f"  Bill (KWHE) : {BILL_EXPORT_KWH:.2f} kWh")
    print(f"  Difference  : {diff:+.2f} kWh ({diff/BILL_EXPORT_KWH*100:+.1f}%)")
else:
    print("  — field not found (export tracking may not be enabled)")

# ── Import ────────────────────────────────────────────────────────────────────
print(f"\n▶ Import from Grid (energy_imported_kwh)")
imp_recs = run_query(flux_import)
if imp_recs:
    app_imp = sum(float(r.get_value() or 0) for r in imp_recs)
    diff = app_imp - BILL_IMPORT_KWH
    print(f"  App total   : {app_imp:.2f} kWh")
    print(f"  Bill (KWHI) : {BILL_IMPORT_KWH:.2f} kWh")
    print(f"  Difference  : {diff:+.2f} kWh ({diff/BILL_IMPORT_KWH*100:+.1f}%)")
else:
    print("  — field not found (import tracking may not be enabled)")

print("\n" + "=" * 60)
client.close()
