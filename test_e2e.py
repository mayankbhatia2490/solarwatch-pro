#!/usr/bin/env python3
"""
SolarWatch Pro — End-to-End Test Suite
Run from the NAS:
    docker compose exec solar-api python /app/test_e2e.py
Or from the NAS host (hits nginx on port 8080):
    python3 test_e2e.py --host http://localhost:8080
"""
import sys, json, time, argparse
from datetime import date, timedelta

try:
    import requests
except ImportError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "requests", "-q"])
    import requests

# ── Config ────────────────────────────────────────────────────────────────────
parser = argparse.ArgumentParser()
parser.add_argument("--host", default="http://localhost:8000",
                    help="Base URL of the API (default: http://localhost:8000 inside container)")
parser.add_argument("--timeout", type=int, default=30)
args = parser.parse_args()

BASE = args.host.rstrip("/")
TIMEOUT = args.timeout
SESSION = requests.Session()

PASS  = "\033[92m✓\033[0m"
FAIL  = "\033[91m✗\033[0m"
WARN  = "\033[93m⚠\033[0m"
INFO  = "\033[94mℹ\033[0m"

results = []

# ── Helpers ───────────────────────────────────────────────────────────────────
def get(path, params=None):
    url = f"{BASE}{path}"
    r = SESSION.get(url, params=params, timeout=TIMEOUT)
    r.raise_for_status()
    return r.json()

def check(name, passed, detail=""):
    icon = PASS if passed else FAIL
    print(f"  {icon} {name}" + (f"  — {detail}" if detail else ""))
    results.append((name, passed, detail))
    return passed

def warn(name, detail=""):
    print(f"  {WARN} {name}" + (f"  — {detail}" if detail else ""))
    results.append((name, None, detail))

def section(title):
    print(f"\n{'─'*60}")
    print(f"  {title}")
    print(f"{'─'*60}")


# ══════════════════════════════════════════════════════════════════════════════
# 1. API HEALTH
# ══════════════════════════════════════════════════════════════════════════════
section("1. API REACHABILITY")

try:
    data = get("/api/dashboard/summary")
    check("API responds to /api/dashboard/summary", True)
    check("Response has power_now_w field", "power_now_w" in data,
          f"keys: {list(data.keys())[:8]}")
except Exception as e:
    check("API responds", False, str(e))
    print(f"\n  {FAIL} Cannot reach API at {BASE}. Is the container running?")
    print(f"  Run: docker compose exec solar-api python /app/test_e2e.py")
    sys.exit(1)


# ══════════════════════════════════════════════════════════════════════════════
# 2. LIVE DASHBOARD SUMMARY
# ══════════════════════════════════════════════════════════════════════════════
section("2. LIVE DASHBOARD SUMMARY")

data = get("/api/dashboard/summary")
check("power_now_w present",     "power_now_w" in data)
check("daily_energy_kwh present","daily_energy_kwh" in data)
check("grid_r_voltage present",  "grid_r_voltage" in data)

pwr = data.get("power_now_w", 0)
daily = data.get("daily_energy_kwh", 0)
print(f"  {INFO} Current power:    {pwr} W")
print(f"  {INFO} Today's energy:   {daily} kWh")
print(f"  {INFO} Grid voltage:     {data.get('grid_r_voltage', '?')} V")
print(f"  {INFO} Inverter temp:    {data.get('internal_radiator_temperature', '?')} °C")

if pwr == 0:
    warn("power_now_w is 0 — expected if it's nighttime or inverter is off")
if daily == 0:
    warn("daily_energy_kwh is 0 — check if collector is writing data")


# ══════════════════════════════════════════════════════════════════════════════
# 3. GENERATION CHART — THE KEY FIX
# ══════════════════════════════════════════════════════════════════════════════
section("3. GENERATION CHART (THE MAIN FIX)")

for rng in ["today", "7d", "yesterday", "1h", "4h"]:
    try:
        t0 = time.time()
        data = get("/api/dashboard/daily-chart", {"range": rng})
        elapsed = time.time() - t0
        pts = data.get("data", [])

        if not pts:
            check(f"chart?range={rng}: has data points", False, "0 points returned")
            continue

        # The critical check: are power_w values non-zero?
        nonzero_actual = [p for p in pts if p.get("power_w", 0) > 0]
        nonzero_expect = [p for p in pts if p.get("expected_w", 0) > 0]

        check(
            f"chart?range={rng}: {len(pts)} points, actual non-zero",
            len(nonzero_actual) > 0,
            f"{len(nonzero_actual)}/{len(pts)} actual>0, {len(nonzero_expect)}/{len(pts)} expected>0  [{elapsed:.1f}s]"
        )

        if nonzero_actual:
            sample = nonzero_actual[len(nonzero_actual)//2]
            print(f"       sample point: time={sample['time'][:16]}  "
                  f"power_w={sample['power_w']}  expected_w={sample['expected_w']}")
        elif nonzero_expect:
            warn(f"  chart?range={rng}: expected_w is non-zero but power_w=0 for all points — "
                 "inverter may be off, or data not written yet today")

    except Exception as e:
        check(f"chart?range={rng}", False, str(e))


# ══════════════════════════════════════════════════════════════════════════════
# 4. PERFORMANCE ANALYSIS
# ══════════════════════════════════════════════════════════════════════════════
section("4. PERFORMANCE ANALYSIS")

for days in [7, 30]:
    try:
        t0 = time.time()
        data = get("/api/analysis", {"days": days})
        elapsed = time.time() - t0

        s = data.get("summary", {})
        bars = data.get("daily_bars", [])
        pr = data.get("pr_trend", [])
        hp = data.get("hourly_profile", [])

        check(f"analysis?days={days}: status=success",
              data.get("status") == "success",
              f"status={data.get('status')}  [{elapsed:.1f}s]")
        check(f"analysis?days={days}: has daily bars",
              len(bars) > 0, f"{len(bars)} days")
        check(f"analysis?days={days}: total_actual_kwh > 0",
              s.get("total_actual_kwh", 0) > 0,
              f"{s.get('total_actual_kwh', 0)} kWh")
        check(f"analysis?days={days}: overall_pr reasonable",
              0 < s.get("overall_pr_pct", 0) <= 110,
              f"PR={s.get('overall_pr_pct', 0)}%")
        check(f"analysis?days={days}: hourly_profile has data",
              any(h.get("avg_actual_w", 0) > 0 for h in hp),
              f"{sum(1 for h in hp if h.get('avg_actual_w',0)>0)}/15 hours have data")

        print(f"  {INFO} Actual: {s.get('total_actual_kwh','?')} kWh  "
              f"Expected: {s.get('total_expected_kwh','?')} kWh  "
              f"PR: {s.get('overall_pr_pct','?')}%  "
              f"Expected source: {data.get('expected_source','?')}")

    except Exception as e:
        check(f"analysis?days={days}", False, str(e))


# ══════════════════════════════════════════════════════════════════════════════
# 5. WEATHER PAGE
# ══════════════════════════════════════════════════════════════════════════════
section("5. WEATHER PAGE")

try:
    data = get("/api/weather")
    cur = data.get("current", {})
    check("weather: has current block",        bool(cur))
    check("weather: temperature_c present",    "temperature_c" in cur,
          f"{cur.get('temperature_c','?')} °C")
    check("weather: poa_irradiance_wm2 present","poa_irradiance_wm2" in cur,
          f"{cur.get('poa_irradiance_wm2','?')} W/m²")
    check("weather: shortwave_radiation present","shortwave_radiation" in cur,
          f"{cur.get('shortwave_radiation','?')} W/m²")
    # These were the broken fields (now renamed)
    check("weather: no direct_radiation key (old broken field)",
          "direct_radiation" not in cur, "would cause NaN if present")
except Exception as e:
    check("weather endpoint", False, str(e))


# ══════════════════════════════════════════════════════════════════════════════
# 6. FORECAST PAGE
# ══════════════════════════════════════════════════════════════════════════════
section("6. FORECAST PAGE")

try:
    t0 = time.time()
    data = get("/api/forecast")
    elapsed = time.time() - t0
    hourly = data.get("hourly", [])
    check("forecast: returns hourly list", len(hourly) > 0, f"{len(hourly)} hours")
    check("forecast: has expected_w field",
          any("expected_w" in h for h in hourly[:5]))
    check("forecast: has irradiance_source",
          "irradiance_source" in data,
          f"source={data.get('irradiance_source','?')}  [{elapsed:.1f}s]")
    nonzero = [h for h in hourly if h.get("expected_w", 0) > 0]
    check("forecast: non-zero expected_w values",
          len(nonzero) > 0, f"{len(nonzero)}/{len(hourly)} hours have expected_w>0")
except Exception as e:
    check("forecast endpoint", False, str(e))


# ══════════════════════════════════════════════════════════════════════════════
# 7. THERMAL PAGE
# ══════════════════════════════════════════════════════════════════════════════
section("7. THERMAL PAGE")

try:
    data = get("/api/thermal")
    cur = data.get("current", {})
    hist = data.get("history", [])
    check("thermal: has current block",        bool(cur))
    check("thermal: radiator_temp present",    "radiator_temp" in cur,
          f"{cur.get('radiator_temp','?')} °C")
    check("thermal: no module_temp key (old broken field)",
          "module_temp" not in cur, "caused thermal page crash")
    check("thermal: module_temperature_c present",
          "module_temperature_c" in cur,
          f"{cur.get('module_temperature_c','?')}")
    check("thermal: history list present",     isinstance(hist, list),
          f"{len(hist)} records")
except Exception as e:
    check("thermal endpoint", False, str(e))


# ══════════════════════════════════════════════════════════════════════════════
# 8. HEALTH SCORECARD
# ══════════════════════════════════════════════════════════════════════════════
section("8. HEALTH SCORECARD")

try:
    data = get("/api/dashboard/health-scorecard")
    rows = data.get("rows", [])
    check("health-scorecard: has rows", len(rows) > 0, f"{len(rows)} rows")
    statuses = {r["parameter"]: r["status"] for r in rows}
    for param, status in statuses.items():
        icon = PASS if status == "normal" else (WARN if status == "warning" else
               FAIL if status == "critical" else INFO)
        print(f"  {icon} {param}: {status}  ({next((r['value'] for r in rows if r['parameter']==param), '?')})")
except Exception as e:
    check("health-scorecard endpoint", False, str(e))


# ══════════════════════════════════════════════════════════════════════════════
# 9. CALIBRATION
# ══════════════════════════════════════════════════════════════════════════════
section("9. CALIBRATION STATUS")

try:
    data = get("/api/calibrate/status")
    factors = data.get("factors", {})
    check("calibration: has factor table", len(factors) > 0,
          f"{len(factors)} months")
    suspicious = data.get("suspicious", False)
    if suspicious:
        warn("calibration: suspicious factors detected",
             "consider Settings → Calibration → Reset to Neutral")
    else:
        check("calibration: no suspicious factors", True)

    may_factor = factors.get("5") or factors.get("May", None)
    if may_factor is not None:
        ok = 0.70 <= float(may_factor) <= 1.40
        check(f"calibration: May factor in valid range (0.70–1.40)",
              ok, f"factor={may_factor}")
except Exception as e:
    check("calibrate/status endpoint", False, str(e))


# ══════════════════════════════════════════════════════════════════════════════
# 10. AI REPORT (GEMINI)
# ══════════════════════════════════════════════════════════════════════════════
section("10. AI REPORT (GEMINI)")

try:
    model_data = get("/api/ai/models")
    will_use = model_data.get("will_use", "?")
    check("AI models endpoint reachable", True, f"will use: {will_use}")
    flash = model_data.get("available_flash_models", [])
    check("Gemini Flash model available", len(flash) > 0,
          f"{len(flash)} flash models: {flash[:3]}")
except requests.HTTPError as e:
    if e.response.status_code == 503:
        warn("AI models: GEMINI_API_KEY not configured — AI report won't work")
    else:
        check("AI models endpoint", False, str(e))
except Exception as e:
    check("AI models endpoint", False, str(e))

# Test insight with days=7 (faster than 30)
try:
    print(f"  {INFO} Calling /api/ai/insight?days=7  (may take 10-30s)...")
    t0 = time.time()
    data = get("/api/ai/insight", {"days": 7})
    elapsed = time.time() - t0

    s = data.get("summary", {})
    report = data.get("ai_report", "")
    check("AI insight: status=success",
          data.get("status") == "success", f"[{elapsed:.1f}s]")
    check("AI insight: summary has actual_kwh > 0",
          s.get("total_actual_kwh", 0) > 0,
          f"actual={s.get('total_actual_kwh','?')} kWh  expected={s.get('total_expected_kwh','?')} kWh")
    check("AI insight: report is non-empty",
          len(report) > 100, f"{len(report)} chars, model={data.get('model','?')}")
    check("AI insight: report looks real (not generic)",
          any(kw in report.lower() for kw in
              ["karnal", "vikram", "ksy", "pr", "performance", "kwh", "%"]),
          "report references system-specific terms")

    if s.get("total_actual_kwh", 0) == 0:
        warn("AI insight: actual_kwh=0 fed to Gemini — report will be generic")

except requests.HTTPError as e:
    if e.response.status_code == 503:
        warn("AI insight: GEMINI_API_KEY not set — skip AI tests")
    else:
        check("AI insight endpoint", False, f"HTTP {e.response.status_code}")
except Exception as e:
    check("AI insight endpoint", False, str(e))


# ══════════════════════════════════════════════════════════════════════════════
# 11. DATA INTEGRITY CHECKS
# ══════════════════════════════════════════════════════════════════════════════
section("11. DATA INTEGRITY")

# Check that collector is actually writing data (heartbeat via summary vs analysis)
try:
    summary = get("/api/dashboard/summary")
    analysis = get("/api/analysis", {"days": 1})
    bars = analysis.get("daily_bars", [])
    today_str = date.today().isoformat()
    today_bar = next((b for b in bars if b["date"] == today_str), None)

    sum_daily = summary.get("daily_energy_kwh", 0)
    ana_daily = today_bar["actual_kwh"] if today_bar else None

    check("data integrity: summary.daily_energy_kwh > 0",
          sum_daily > 0, f"{sum_daily} kWh")

    if ana_daily is not None:
        diff = abs(sum_daily - ana_daily)
        check("data integrity: summary vs analysis daily_energy agree",
              diff < 1.0, f"summary={sum_daily} kWh, analysis={ana_daily} kWh, diff={diff:.2f}")
    else:
        warn("data integrity: today not yet in analysis bars (could be UTC boundary)")

    # Check PR sanity
    s = analysis.get("summary", {})
    pr = s.get("overall_pr_pct", 0)
    if pr > 110:
        warn(f"data integrity: PR={pr}% > 110% — calibration factor too low, reset recommended")
    elif pr > 0:
        check("data integrity: PR in plausible range (0–110%)",
              True, f"PR={pr}%")

except Exception as e:
    check("data integrity checks", False, str(e))

# Check that 7d chart power_w matches what InfluxDB has
try:
    chart7d = get("/api/dashboard/daily-chart", {"range": "7d"})
    pts = chart7d.get("data", [])
    if pts:
        all_zero = all(p.get("power_w", 0) == 0 for p in pts)
        check("data integrity: 7d chart power_w not all-zero",
              not all_zero,
              f"{'ALL ZERO — InfluxDB/aggregateWindow issue' if all_zero else f'{sum(1 for p in pts if p[\"power_w\"]>0)}/{len(pts)} non-zero'}")
    else:
        warn("data integrity: 7d chart returned no points")
except Exception as e:
    check("data integrity: 7d chart", False, str(e))


# ══════════════════════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════════════════════
passed = [r for r in results if r[1] is True]
failed = [r for r in results if r[1] is False]
warned = [r for r in results if r[1] is None]

print(f"\n{'═'*60}")
print(f"  RESULTS: {len(passed)} passed  {len(failed)} failed  {len(warned)} warnings")
print(f"{'═'*60}")

if failed:
    print(f"\n  {FAIL} FAILURES:")
    for name, _, detail in failed:
        print(f"    • {name}" + (f": {detail}" if detail else ""))

if warned:
    print(f"\n  {WARN} WARNINGS:")
    for name, _, detail in warned:
        print(f"    • {name}" + (f": {detail}" if detail else ""))

if not failed:
    print(f"\n  {PASS} All checks passed!")
else:
    print(f"\n  Run with --host to test a different target.")
    print(f"  Example: python3 test_e2e.py --host http://localhost:8080")

sys.exit(0 if not failed else 1)
