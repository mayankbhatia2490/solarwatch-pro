from fastapi import APIRouter, HTTPException
from typing import Dict, Any
from datetime import datetime, timezone, timedelta
from influx import query
from config import settings

router = APIRouter(prefix="/api/anomalies", tags=["Anomalies"])

BUCKET = settings.influxdb_bucket

# Thresholds aligned with monitor.py — single source per router
TEMP_WARN     = 75.0
TEMP_CRIT     = 85.0
GRID_V_LOW    = 207.0
GRID_V_HIGH   = 253.0
FREQ_LOW      = 49.5
FREQ_HIGH     = 50.5
STRING_IMBAL  = 0.20   # 20% power deviation between strings


@router.get("/")
def get_anomalies(days: int = 7) -> Dict[str, Any]:
    """
    Scans real InfluxDB data and surfaces actual anomalies.
    No mock/hardcoded events — every entry has a real timestamp and measured value.
    """
    try:
        # Pull hourly-max pivot for all anomaly-relevant fields
        flux = f'''
from(bucket: "{BUCKET}")
  |> range(start: -{days}d)
  |> filter(fn: (r) =>
        r["_field"] == "internal_radiator_temperature" or
        r["_field"] == "grid_r_voltage" or
        r["_field"] == "grid_frequency" or
        r["_field"] == "power_now_w" or
        r["_field"] == "expected_power_w" or
        r["_field"] == "pv1_voltage" or
        r["_field"] == "pv1_current" or
        r["_field"] == "pv2_voltage" or
        r["_field"] == "pv2_current" or
        r["_field"] == "shortwave_radiation_wm2")
  |> aggregateWindow(every: 1h, fn: mean, createEmpty: false)
  |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
  |> sort(columns: ["_time"], desc: true)
'''
        records = query(flux)

        anomalies = []
        _id = 1

        for r in records:
            v = r.values
            time_iso = r.get_time().isoformat()

            # ── 1. Temperature ────────────────────────────────────────────────
            temp = v.get("internal_radiator_temperature")
            if temp and temp > TEMP_WARN:
                severity = "critical" if temp > TEMP_CRIT else "warning"
                loss_w = 0
                # Thermal derating: above 75°C KSY derates ~1% per °C
                if temp > TEMP_WARN:
                    derate_pct = min((temp - TEMP_WARN) * 1.0, 30.0)
                    power = v.get("power_now_w") or 0
                    loss_w = round(power * derate_pct / 100)

                tariff = settings.electricity_tariff_inr
                impact_inr = round(loss_w / 1000 * tariff, 1)

                anomalies.append({
                    "id": f"temp-{_id}",
                    "timestamp": time_iso,
                    "severity": severity,
                    "source": "Intelligence",
                    "parameter": f"{temp:.1f}°C",
                    "title": "Inverter Overheating",
                    "description": (
                        f"Heatsink temperature reached {temp:.1f}°C "
                        f"({'critical — F8 fault risk' if temp > TEMP_CRIT else 'warning — approaching protection limit'})."
                    ),
                    "impact_inr": impact_inr,
                    "action": "Check inverter ventilation. Ensure no dust blockage on heatsink fins."
                })
                _id += 1

            # ── 2. Grid voltage ───────────────────────────────────────────────
            gv = v.get("grid_r_voltage")
            if gv and (gv < GRID_V_LOW or gv > GRID_V_HIGH):
                direction = "low" if gv < GRID_V_LOW else "high"
                anomalies.append({
                    "id": f"grid-v-{_id}",
                    "timestamp": time_iso,
                    "severity": "warning",
                    "source": "Intelligence",
                    "parameter": f"{gv:.1f}V",
                    "title": f"Grid Voltage {direction.title()} ({gv:.0f}V)",
                    "description": (
                        f"Grid R-phase voltage {gv:.1f}V is outside the safe 207–253V range. "
                        f"This is a grid-side issue — your inverter may trip to protect itself."
                    ),
                    "impact_inr": 0,
                    "action": "Monitor. If persistent, contact your electricity distributor (UHBVN)."
                })
                _id += 1

            # ── 3. Grid frequency ─────────────────────────────────────────────
            freq = v.get("grid_frequency")
            if freq and freq > 0 and (freq < FREQ_LOW or freq > FREQ_HIGH):
                anomalies.append({
                    "id": f"grid-f-{_id}",
                    "timestamp": time_iso,
                    "severity": "warning",
                    "source": "Intelligence",
                    "parameter": f"{freq:.2f}Hz",
                    "title": f"Grid Frequency Out of Range ({freq:.2f}Hz)",
                    "description": (
                        f"Grid frequency {freq:.2f}Hz is outside normal 49.5–50.5Hz. "
                        f"Grid instability — inverter will disconnect automatically if it continues."
                    ),
                    "impact_inr": 0,
                    "action": "No action needed. Inverter protects itself automatically."
                })
                _id += 1

            # ── 4. Near-zero output during daylight ───────────────────────────
            power = v.get("power_now_w") or 0
            radiation = v.get("shortwave_radiation_wm2") or 0
            expected = v.get("expected_power_w") or 0

            if radiation > 300 and expected > 200:
                efficiency = power / expected if expected > 0 else 1.0
                if efficiency < 0.15:  # less than 15% of expected = near-zero
                    tariff = settings.electricity_tariff_inr
                    lost_kwh = (expected - power) / 1000
                    impact_inr = round(lost_kwh * tariff, 1)
                    anomalies.append({
                        "id": f"zero-{_id}",
                        "timestamp": time_iso,
                        "severity": "critical",
                        "source": "Intelligence",
                        "parameter": f"{power:.0f}W / {expected:.0f}W expected",
                        "title": "Near-Zero Output During Daylight",
                        "description": (
                            f"System producing only {power:.0f}W against {expected:.0f}W expected "
                            f"({efficiency*100:.0f}% efficiency) with {radiation:.0f} W/m² solar radiation."
                        ),
                        "impact_inr": impact_inr,
                        "action": "Check inverter display for fault codes. Verify DC disconnect is closed."
                    })
                    _id += 1

                elif efficiency < 0.50:  # 15–50% = significant underperformance
                    tariff = settings.electricity_tariff_inr
                    lost_kwh = (expected - power) / 1000
                    impact_inr = round(lost_kwh * tariff, 1)
                    anomalies.append({
                        "id": f"low-{_id}",
                        "timestamp": time_iso,
                        "severity": "warning",
                        "source": "Intelligence",
                        "parameter": f"{efficiency*100:.0f}% of expected",
                        "title": "Significant Output Underperformance",
                        "description": (
                            f"System at {power:.0f}W vs {expected:.0f}W expected ({efficiency*100:.0f}%). "
                            f"Possible causes: panel soiling, partial shading, or string issue."
                        ),
                        "impact_inr": impact_inr,
                        "action": "Check for panel soiling or shading. Inspect string connections."
                    })
                    _id += 1

            # ── 5. String power imbalance ─────────────────────────────────────
            pv1_v = v.get("pv1_voltage") or 0
            pv1_a = v.get("pv1_current") or 0
            pv2_v = v.get("pv2_voltage") or 0
            pv2_a = v.get("pv2_current") or 0
            pv1_power = pv1_v * pv1_a
            pv2_power = pv2_v * pv2_a

            if pv1_power > 50 and pv2_power > 50 and radiation > 200:
                max_power = max(pv1_power, pv2_power)
                imbalance = abs(pv1_power - pv2_power) / max_power
                if imbalance > STRING_IMBAL:
                    weaker = "String 1" if pv1_power < pv2_power else "String 2"
                    weaker_w = min(pv1_power, pv2_power)
                    stronger_w = max(pv1_power, pv2_power)
                    lost_w = stronger_w - weaker_w
                    impact_inr = round(lost_w / 1000 * settings.electricity_tariff_inr, 1)
                    anomalies.append({
                        "id": f"imbal-{_id}",
                        "timestamp": time_iso,
                        "severity": "warning",
                        "source": "Intelligence",
                        "parameter": f"{imbalance*100:.0f}% imbalance",
                        "title": f"String Power Imbalance — {weaker} Underperforming",
                        "description": (
                            f"String 1: {pv1_power:.0f}W | String 2: {pv2_power:.0f}W. "
                            f"{weaker} is producing {imbalance*100:.0f}% less than expected. "
                            f"Likely cause: soiling, shading, or a loose MC4 connector on {weaker}."
                        ),
                        "impact_inr": impact_inr,
                        "action": f"Inspect {weaker} panels for dirt, bird droppings, or shading objects."
                    })
                    _id += 1

        # Deduplicate: keep only the most severe occurrence per anomaly type per day
        # (hourly scan can produce many rows for a persistent condition)
        seen: dict[str, str] = {}  # key → date string of first occurrence
        deduped = []
        for a in anomalies:
            day = a["timestamp"][:10]
            key = f"{a['title']}:{day}"
            if key not in seen:
                seen[key] = day
                deduped.append(a)

        deduped.sort(key=lambda x: x["timestamp"], reverse=True)
        return {"status": "success", "data": deduped}

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
