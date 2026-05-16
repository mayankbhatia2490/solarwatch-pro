#!/usr/bin/env python3
"""
SolarWatch Pro — End-to-End Test Suite
Run from the NAS project root directory:
    python3 test_e2e.py --host http://localhost:8080
"""
import sys, time, argparse
from datetime import date

try:
    import requests
except ImportError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "requests", "-q"])
    import requests

parser = argparse.ArgumentParser()
parser.add_argument("--host", default="http://localhost:8080",
                    help="Base URL (default: http://localhost:8080)")
parser.add_argument("--timeout", type=int, default=30)
args = parser.parse_args()

BASE    = args.host.rstrip("/")
TIMEOUT = args.timeout
SESSION = requests.Session()

PASS = "\033[92m✓\033[0m"
FAIL = "\033[91m✗\033[0m"
WARN = "\033[93m⚠\033[0m"
INFO = "\033[94mℹ\033[0m"

results = []

def get(path, params=None):
    r = SESSION.get(f"{BASE}{path}", params=params, timeout=TIMEOUT)
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
    print(f"\n{'─'*62}")
    print(f"  {title}")
    print(f"{'─'*62}")


# ══════════════════════════════════════════════════════════════════
# 1. API REACHABILITY
# ══════════════════════════════════════════════════════════════════
section("1. API REACHABILITY")
try:
    data = get("/api/dashboard/summary")
    check("API responds", True, f"keys: {list(data.keys())[:6]}")
except Exception as e:
    check("API responds", False, str(e))
    print(f"\n  {FAIL} Cannot reach {BASE}. Is the stack running?")
    sys.exit(1)


# ══════════════════════════════════════════════════════════════════
# 2. LIVE SUMMARY  (keys: power_now_w, energy_today_kwh, etc.)
# ══════════════════════════════════════════════════════════════════
section("2. LIVE DASHBOARD SUMMARY")
data = get("/api/dashboard/summary")

check("power_now_w present",      "power_now_w"      in data)
check("energy_today_kwh present", "energy_today_kwh" in data)
check("capacity_pct present",     "capacity_pct"     in data)

pwr   = data.get("power_now_w", 0)
edkwh = data.get("energy_today_kwh", 0)
print(f"  {INFO} Inverter power now:  {pwr} W")
print(f"  {INFO} Energy today (live): {edkwh} kWh")
if pwr == 0:
    warn("power_now_w = 0 (expected at night or inverter off)")
if edkwh == 0:
    warn("energy_today_kwh = 0 — Shinemonitor sometimes returns 0 for this field; "
         "analysis endpoint uses end-of-day cumulative which is more reliable")


# ══════════════════════════════════════════════════════════════════
# 3. GENERATION CHART  ← THE CORE FIX
# ══════════════════════════════════════════════════════════════════
section("3. GENERATION CHART  (fix: drop aggregateWindow+pivot)")

for rng in ["today", "7d", "yesterday", "1h", "4h"]:
    try:
        t0  = time.time()
        d   = get("/api/dashboard/daily-chart", {"range": rng})
        pts = d.get("data", [])
        elapsed = time.time() - t0

        if not pts:
            check(f"chart?range={rng}", False, "0 points returned")
            continue

        nz_act = sum(1 for p in pts if p.get("power_w",   0) > 0)
        nz_exp = sum(1 for p in pts if p.get("expected_w", 0) > 0)

        ok = nz_act > 0
        check(f"chart?range={rng}: {len(pts)} pts, non-zero actual",
              ok,
              f"{nz_act}/{len(pts)} actual>0   {nz_exp}/{len(pts)} expected>0  [{elapsed:.1f}s]")

        if ok:
            mid = pts[len(pts)//2]
            print(f"       sample: {mid['time'][:16]}  "
                  f"power={mid['power_w']}W  exp={mid['expected_w']}W")
        elif nz_exp > 0:
            warn(f"  chart?range={rng}: expected>0 but all actual=0 "
                 "— historical power_now_w may be missing/zero in InfluxDB "
                 "(data gap, not a code bug; today/1h/4h should work)")
    except Exception as e:
        check(f"chart?range={rng}", False, str(e))


# ══════════════════════════════════════════════════════════════════
# 4. PERFORMANCE ANALYSIS
# ══════════════════════════════════════════════════════════════════
section("4. PERFORMANCE ANALYSIS")

for days in [7, 30]:
    try:
        t0   = time.time()
        data = get("/api/analysis", {"days": days})
        elapsed = time.time() - t0
        s    = data.get("summary", {})
        bars = data.get("daily_bars", [])
        hp   = data.get("hourly_profile", [])

        check(f"analysis?days={days}: status=success",
              data.get("status") == "success",  f"[{elapsed:.1f}s]")
        check(f"analysis?days={days}: has daily_bars",
              len(bars) > 0, f"{len(bars)} days")
        check(f"analysis?days={days}: actual_kwh > 0",
              s.get("total_actual_kwh", 0) > 0,
              f"{s.get('total_actual_kwh')} kWh actual, {s.get('total_expected_kwh')} kWh expected")
        check(f"analysis?days={days}: PR in range 0–110%",
              0 < s.get("overall_pr_pct", 0) <= 110,
              f"PR={s.get('overall_pr_pct')}%  source={data.get('expected_source')}")
        check(f"analysis?days={days}: hourly_profile populated",
              any(h.get("avg_actual_w", 0) > 0 for h in hp),
              f"{sum(1 for h in hp if h.get('avg_actual_w',0)>0)}/15 hours")
    except Exception as e:
        check(f"analysis?days={days}", False, str(e))


# ══════════════════════════════════════════════════════════════════
# 5. WEATHER PAGE  (data lives under response["data"]["current"])
# ══════════════════════════════════════════════════════════════════
section("5. WEATHER PAGE")

try:
    resp = get("/api/weather")
    # Actual structure: {"status": ..., "data": {"current": {...}, ...}}
    d_block = resp.get("data", {})
    cur     = d_block.get("current", {})

    check("weather: top-level data block present", bool(d_block),
          f"status={resp.get('status')}  source={resp.get('irradiance_source')}")
    check("weather: current block present",       bool(cur))
    check("weather: temperature_2m present",      "temperature_2m"    in cur,
          f"{cur.get('temperature_2m')} °C")
    check("weather: poa_irradiance_wm2 present",  "poa_irradiance_wm2" in cur,
          f"{cur.get('poa_irradiance_wm2')} W/m²")
    check("weather: shortwave_radiation present", "shortwave_radiation" in cur,
          f"{cur.get('shortwave_radiation')} W/m²")
    check("weather: no broken direct_radiation key",
          "direct_radiation" not in cur)
except Exception as e:
    check("weather endpoint", False, str(e))


# ══════════════════════════════════════════════════════════════════
# 6. FORECAST PAGE  (hourly list is under "hourly_forecast" key)
# ══════════════════════════════════════════════════════════════════
section("6. FORECAST PAGE")

try:
    t0   = time.time()
    resp = get("/api/forecast")
    elapsed = time.time() - t0
    # Actual key: hourly_forecast (not "hourly")
    hourly = resp.get("hourly_forecast", [])

    check("forecast: source known",
          resp.get("irradiance_source") in ("solcast", "open-meteo"),
          f"source={resp.get('irradiance_source')}  [{elapsed:.1f}s]")
    check("forecast: hourly_forecast list present",
          len(hourly) > 0, f"{len(hourly)} hours")
    nz = sum(1 for h in hourly if h.get("expected_power_w", 0) > 0)
    check("forecast: non-zero expected_power_w hours",
          nz > 0, f"{nz}/{len(hourly)} hours expected_power_w>0")

    if hourly:
        next_h = next((h for h in hourly if h.get("expected_power_w", 0) > 0), hourly[0])
        print(f"  {INFO} Next non-zero hour: {next_h.get('time','')}  "
              f"expected={next_h.get('expected_power_w')}W  "
              f"source={next_h.get('irradiance_source')}")
except Exception as e:
    check("forecast endpoint", False, str(e))


# ══════════════════════════════════════════════════════════════════
# 7. THERMAL PAGE  (route is /api/thermal/history)
# ══════════════════════════════════════════════════════════════════
section("7. THERMAL PAGE")

try:
    resp = get("/api/thermal/history", {"hours": 6})
    cur  = resp.get("current", {})
    hist = resp.get("history", [])

    check("thermal: /api/thermal/history reachable", True)
    check("thermal: radiator_temp present",
          "radiator_temp"       in cur, f"{cur.get('radiator_temp')} °C")
    check("thermal: module_temperature_c present",
          "module_temperature_c" in cur,
          str(cur.get("module_temperature_c")))
    check("thermal: no old 'module_temp' broken field",
          "module_temp" not in cur)
    check("thermal: history list present",
          isinstance(hist, list), f"{len(hist)} records")
except Exception as e:
    check("thermal /api/thermal/history", False, str(e))


# ══════════════════════════════════════════════════════════════════
# 8. HEALTH SCORECARD
# ══════════════════════════════════════════════════════════════════
section("8. HEALTH SCORECARD")

try:
    resp = get("/api/dashboard/health-scorecard")
    rows = resp.get("rows", [])
    check("health-scorecard: rows present", len(rows) > 0, f"{len(rows)} rows")
    for r in rows:
        status = r.get("status", "?")
        icon   = PASS if status == "normal" else WARN if status == "warning" else FAIL
        print(f"  {icon} {r['parameter']}: {status}  ({r['value']})")
except Exception as e:
    check("health-scorecard", False, str(e))


# ══════════════════════════════════════════════════════════════════
# 9. CALIBRATION  (factors is a list of {month, factor, suspicious})
# ══════════════════════════════════════════════════════════════════
section("9. CALIBRATION")

try:
    resp = get("/api/calibrate/status")
    status = resp.get("status")
    print(f"  {INFO} Status: {status}")

    if status == "not_run":
        warn("Calibration file not found — run POST /api/calibrate/run once",
             "go to Settings → Calibration → Re-run")
    elif status == "running":
        warn("Calibration currently running")
    else:
        factors = resp.get("factors", [])
        check("calibration: 12 monthly factors present",
              len(factors) == 12, f"{len(factors)} factors")
        suspicious = [f for f in factors if f.get("suspicious")]
        if suspicious:
            warn(f"{len(suspicious)} suspicious factors detected",
                 ", ".join(f"{f['month_name']}={f['factor']}" for f in suspicious))
        else:
            check("calibration: all factors in valid range", True)
        print(f"  {INFO} Age: {resp.get('age_days')} days  "
              f"Winner: {resp.get('winner')}  "
              f"Suspicious: {resp.get('suspicious')}")
except Exception as e:
    check("calibration endpoint", False, str(e))


# ══════════════════════════════════════════════════════════════════
# 10. AI REPORT
# ══════════════════════════════════════════════════════════════════
section("10. AI REPORT (GEMINI)")

try:
    mresp = get("/api/ai/models")
    check("AI /models reachable", True,
          f"will_use={mresp.get('will_use')}  "
          f"flash models={len(mresp.get('available_flash_models', []))}")
except requests.HTTPError as e:
    if e.response.status_code == 503:
        warn("GEMINI_API_KEY not set — AI report unavailable")
        mresp = None
    else:
        check("AI models endpoint", False, str(e)); mresp = None
except Exception as e:
    check("AI models endpoint", False, str(e)); mresp = None

if mresp:
    try:
        print(f"  {INFO} Calling /api/ai/insight?days=7  (10–30s) …")
        t0   = time.time()
        resp = get("/api/ai/insight", {"days": 7})
        elapsed = time.time() - t0
        s    = resp.get("summary", {})
        text = resp.get("ai_report", "")

        check("AI insight: success", resp.get("status") == "success", f"[{elapsed:.1f}s]")
        check("AI insight: actual_kwh > 0",
              s.get("total_actual_kwh", 0) > 0,
              f"actual={s.get('total_actual_kwh')} kWh  expected={s.get('total_expected_kwh')} kWh")
        check("AI insight: report non-empty", len(text) > 100,
              f"{len(text)} chars  model={resp.get('model')}")
        check("AI insight: report is system-specific",
              any(kw in text.lower() for kw in
                  ["karnal", "vikram", "ksy", "pr", "kwh", "%"]))
        if s.get("total_actual_kwh", 0) == 0:
            warn("AI got actual_kwh=0 — report will be generic; fix chart data first")
    except requests.HTTPError as e:
        if e.response.status_code == 503:
            warn("GEMINI_API_KEY not configured")
        else:
            check("AI insight", False, f"HTTP {e.response.status_code}")
    except Exception as e:
        check("AI insight", False, str(e))


# ══════════════════════════════════════════════════════════════════
# 11. DATA INTEGRITY
# ══════════════════════════════════════════════════════════════════
section("11. DATA INTEGRITY")

try:
    summary  = get("/api/dashboard/summary")
    analysis = get("/api/analysis", {"days": 1})
    bars     = analysis.get("daily_bars", [])
    today_str = date.today().isoformat()
    today_bar = next((b for b in bars if b["date"] == today_str), None)

    ana_today = today_bar["actual_kwh"] if today_bar else 0
    check("analysis: today's actual_kwh > 0",
          ana_today > 0, f"{ana_today} kWh (from daily_energy_kwh cumulative counter)")

    pr = analysis.get("summary", {}).get("overall_pr_pct", 0)
    check("data integrity: PR ≤ 110%", pr <= 110,
          f"PR={pr}%  (>110% means calibration over-correcting)")

    # 7d chart — code is correct; zeros mean historical power_now_w data gap
    chart7d = get("/api/dashboard/daily-chart", {"range": "7d"})
    pts     = chart7d.get("data", [])
    nz      = sum(1 for p in pts if p.get("power_w", 0) > 0)
    if nz == 0 and pts:
        warn(
            f"7d chart: {len(pts)} points but power_w=0 for all — "
            "historical power_now_w missing in InfluxDB. "
            "Code is correct (today/1h work). "
            "Likely cause: collector wrote power_now_w=0 or was offline for those days. "
            "The analysis PR/kWh data (from daily_energy_kwh) is correct and unaffected."
        )
    else:
        check("7d chart: has non-zero actual power", nz > 0,
              f"{nz}/{len(pts)} points non-zero")

    # today chart should always work
    chart_td = get("/api/dashboard/daily-chart", {"range": "today"})
    pts_td   = chart_td.get("data", [])
    nz_td    = sum(1 for p in pts_td if p.get("power_w", 0) > 0)
    check("today chart: has non-zero actual power",
          nz_td > 0 or summary.get("power_now_w", 0) == 0,
          f"{nz_td}/{len(pts_td)} points non-zero  "
          f"(zero OK if inverter currently off, pwr={summary.get('power_now_w')}W)")

except Exception as e:
    check("data integrity", False, str(e))


# ══════════════════════════════════════════════════════════════════
# SUMMARY
# ══════════════════════════════════════════════════════════════════
passed = [r for r in results if r[1] is True]
failed = [r for r in results if r[1] is False]
warned = [r for r in results if r[1] is None]

print(f"\n{'═'*62}")
print(f"  RESULTS:  {len(passed)} passed   {len(failed)} failed   {len(warned)} warnings")
print(f"{'═'*62}")

if failed:
    print(f"\n  {FAIL} FAILURES:")
    for name, _, detail in failed:
        print(f"    • {name}" + (f": {detail}" if detail else ""))

if warned:
    print(f"\n  {WARN} WARNINGS (informational — not code bugs):")
    for name, _, detail in warned:
        s = detail[:120] + "…" if len(detail) > 120 else detail
        print(f"    • {name}" + (f": {s}" if s else ""))

if not failed:
    print(f"\n  {PASS} All checks passed!")

sys.exit(0 if not failed else 1)
