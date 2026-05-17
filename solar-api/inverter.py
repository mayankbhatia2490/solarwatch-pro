"""
KSolar 5G-PRO+ inverter knowledge base for SolarWatch Pro.
Model: KSY-3.4KW-1Ph  (Single phase, single MPPT, 550V max DC)
Source: 5G-PRO+ Technical Datasheet + User Manual 2024 (KSolare Technology, Pune)

Used by dashboard and diagnostics endpoints to:
  - Decode Shinemonitor fault codes → human-readable name + cause + fix
  - Calculate real DC→AC efficiency vs 98% spec
  - Assess PV string voltage headroom vs 550V absolute max
  - Explain thermal state in context of this inverter's operating limits
"""

# ── Hardware constants ────────────────────────────────────────────────────────
RATED_AC_W         = 3400    # Rated AC output (nameplate)
MAX_DC_INPUT_W     = 3800    # Max DC input (12% oversize ratio over rated AC)
MAX_DC_VOLTAGE_V   = 550     # Absolute max PV string voltage — F5 trips if exceeded
MIN_START_VOLTAGE_V = 50     # Minimum DC to start MPPT tracking
MPPT_MIN_V         = 70      # MPPT lower tracking bound
MPPT_MAX_V         = 550     # MPPT upper tracking bound
MAX_INPUT_CURRENT_A = 20     # Max MPPT input current per string
NUM_MPPT           = 1       # Single MPPT — all panels share one tracker
NUM_STRINGS        = 1       # Single string (no Y-connector)
MAX_EFFICIENCY     = 0.980   # 98.0% peak DC→AC efficiency
EURO_EFFICIENCY    = 0.975   # 97.5% Euro efficiency (weighted partial-load average)
AMBIENT_MAX_C      = 60      # Operating limit — F8 trips approaching this
AMBIENT_PEAK_C     = 45      # Above this, smart fan runs and output may derate
VOLTAGE_WARN_V     = 480     # Alert threshold — approaching 550V limit
VOLTAGE_CAUTION_V  = 400     # Caution threshold

# ── Fault code table (F0–F19) ─────────────────────────────────────────────────
# Source: User Manual Section 9 — Fault Finding + Grid/DC/Inverter fault tables
FAULT_CODES: dict[str, dict] = {
    "F0": {
        "name":     "10-min average voltage over protection range",
        "type":     "AC Grid",
        "cause":    "Grid voltage sustained outside limits for >10 minutes",
        "action":   "Check R-N voltage (should be 140–300V). Contact UHBVN if persistent.",
        "severity": "warning",
    },
    "F1": {
        "name":     "MCU fault",
        "type":     "Inverter Internal",
        "cause":    "Microcontroller unit failure",
        "action":   "Power cycle (DC off → AC off → wait 5 min → restart). If repeated, contact KSolar: 8530111222",
        "severity": "critical",
    },
    "F2": {
        "name":     "Current sensor fault",
        "type":     "Inverter Internal",
        "cause":    "AC or DC current measurement sensor failure",
        "action":   "Power cycle. If persistent, hardware fault — log at https://bit.ly/3eRZba9",
        "severity": "critical",
    },
    "F3": {
        "name":     "GFCI sensor fault",
        "type":     "Inverter Internal",
        "cause":    "Ground fault current interrupter sensor failure",
        "action":   "Power cycle. If persistent, contact KSolar service.",
        "severity": "critical",
    },
    "F4": {
        "name":     "Relay fault",
        "type":     "Inverter Internal",
        "cause":    "Internal relay failed to open or close correctly",
        "action":   "Power cycle. Repeated F4 = hardware failure — contact KSolar: 8530111222",
        "severity": "critical",
    },
    "F5": {
        "name":     "PV voltage too high",
        "type":     "DC Panel Side",
        "cause":    "String voltage exceeds 550V limit — cold morning with high irradiance",
        "action":   "Check DC string voltage. KSY-3.4kW max = 550V. 6 panels × ~46V Voc = ~276V — should be safe. Verify no extra panels were added.",
        "severity": "warning",
    },
    "F6": {
        "name":     "Surface insulation resistance error",
        "type":     "DC Panel Side",
        "cause":    "Ground fault detected — damaged cable, water ingress, or loose MC4 connector",
        "action":   "Check DC+ and DC– to ground resistance. Inspect all MC4 connectors and cable insulation at roof penetrations.",
        "severity": "critical",
    },
    "F7": {
        "name":     "GFCI ground fault current out of range",
        "type":     "DC Panel Side",
        "cause":    "Leakage current to earth exceeds safe limit — water ingress or insulation breakdown",
        "action":   "Disconnect DC immediately. Inspect panels and DC cables for moisture or damage. Do not re-energise until fault is traced.",
        "severity": "critical",
    },
    "F8": {
        "name":     "Temperature out of range",
        "type":     "Thermal",
        "cause":    "Inverter ambient temperature exceeded +60°C (or below –25°C). Common in May–June.",
        "action":   "Ensure 300mm clearance on all four sides. Verify smart fan is spinning. Add a shade awning if wall-mounted in direct sun.",
        "severity": "warning",
    },
    "F9": {
        "name":     "No grid",
        "type":     "AC Grid",
        "cause":    "AC grid disconnected, main CB tripped, or grid power cut",
        "action":   "Check AC circuit breaker at distribution board. Confirm UHBVN grid supply is live.",
        "severity": "warning",
    },
    "F10": {
        "name":     "Grid voltage out of range",
        "type":     "AC Grid",
        "cause":    "R-phase voltage outside 140–300V — grid disturbance or wiring fault",
        "action":   "Measure R-N voltage at inverter AC terminal. Contact UHBVN if voltage is consistently outside 200–250V.",
        "severity": "warning",
    },
    "F11": {
        "name":     "Grid frequency out of range",
        "type":     "AC Grid",
        "cause":    "Grid frequency outside 47–52Hz — grid instability or local load switching",
        "action":   "Monitor frequency; inverter will auto-reconnect when grid normalises. Repeated F11 = contact UHBVN.",
        "severity": "warning",
    },
    "F12": {
        "name":     "DC component out of range",
        "type":     "Inverter Internal",
        "cause":    "DC bias injected into AC output exceeds safety limit",
        "action":   "Power cycle. If repeated, inverter hardware issue — contact KSolar.",
        "severity": "critical",
    },
    "F13": {
        "name":     "EEPROM fault",
        "type":     "Inverter Internal",
        "cause":    "Non-volatile memory failure — configuration settings may be lost",
        "action":   "Power cycle. Firmware re-flash may be required — contact KSolar: 8530111222",
        "severity": "critical",
    },
    "F14": {
        "name":     "Master/slave DSP communication failure",
        "type":     "Inverter Internal",
        "cause":    "Internal processor communication lost",
        "action":   "Power cycle. If repeated, hardware fault — log at https://bit.ly/3eRZba9",
        "severity": "critical",
    },
    "F15": {
        "name":     "BUS voltage too high",
        "type":     "Inverter Internal",
        "cause":    "Internal DC bus overvoltage",
        "action":   "Power cycle. If repeated, hardware fault — contact KSolar.",
        "severity": "critical",
    },
    "F16": {
        "name":     "BUS voltage too low",
        "type":     "Inverter Internal",
        "cause":    "Internal DC bus undervoltage — PV input too low or hardware fault",
        "action":   "Check PV string voltage (must be >70V for MPPT to start). Power cycle.",
        "severity": "warning",
    },
    "F17": {
        "name":     "DRM S9 fault",
        "type":     "Grid Interface",
        "cause":    "Demand Response Management signal fault at COM2 port",
        "action":   "Check DRED/DRM wiring at COM2 port. Not applicable for most India installations — can be ignored if no DRED device connected.",
        "severity": "info",
    },
    "F18": {
        "name":     "DRM S0 fault",
        "type":     "Grid Interface",
        "cause":    "Demand Response Management signal fault",
        "action":   "Check DRED/DRM wiring at COM2 port.",
        "severity": "info",
    },
    "F19": {
        "name":     "N-PE voltage too high",
        "type":     "AC Grid",
        "cause":    "Neutral-to-ground voltage >15V — wiring issue or shared neutral problem",
        "action":   "Measure N-PE voltage at inverter terminal. Check AC neutral and earth wiring at DB. Common in areas with poor earthing.",
        "severity": "warning",
    },
}


def decode_fault(fault_code: str | None) -> dict | None:
    """Decode a KSolar fault code string (e.g. 'F8') into human-readable detail."""
    if not fault_code:
        return None
    code = str(fault_code).strip().upper()
    info = FAULT_CODES.get(code)
    if info:
        return {"code": code, **info}
    return {
        "code": code,
        "name": "Unknown fault code",
        "type": "Unknown",
        "cause": f"Fault code '{code}' not in KSolar F0–F19 table",
        "action": "Power cycle inverter. If repeated, contact KSolar: 8530111222",
        "severity": "warning",
    }


def dc_ac_efficiency(power_ac_w: float, pv1_v: float, pv1_a: float) -> float | None:
    """
    Real-time DC→AC conversion efficiency.
    Spec: 98.0% peak, 97.5% Euro (partial-load weighted).
    Returns None when DC power is too low to be meaningful (<50W).
    """
    dc_w = pv1_v * pv1_a
    if dc_w < 50 or power_ac_w <= 0:
        return None
    eff = round(power_ac_w / dc_w * 100, 1)
    # Cap at 100% — sensor noise can give slightly >100% at very low power
    return min(eff, 100.0)


def efficiency_context(eff_pct: float | None, power_ac_w: float) -> dict:
    """Interpret the efficiency reading relative to KSolar spec."""
    if eff_pct is None:
        return {"status": "no_data", "label": "—", "detail": "Insufficient DC power for measurement"}
    load_pct = round(power_ac_w / RATED_AC_W * 100, 0)
    if eff_pct >= 97:
        status = "excellent"
        label  = f"{eff_pct:.1f}% — near spec peak"
        detail = f"At {load_pct:.0f}% load. Spec: 98.0% peak / 97.5% Euro."
    elif eff_pct >= 94:
        status = "good"
        label  = f"{eff_pct:.1f}% — good"
        detail = f"At {load_pct:.0f}% load. Slight below-spec — normal at partial load or warm conditions."
    elif eff_pct >= 88:
        status = "low"
        label  = f"{eff_pct:.1f}% — below normal"
        detail = f"At {load_pct:.0f}% load. Expected ≥94% at this load. Check for panel soiling, shading, or inverter thermal derating."
    else:
        status = "poor"
        label  = f"{eff_pct:.1f}% — very low"
        detail = f"At {load_pct:.0f}% load. Significant loss — check for fault, soiling, or partial shading on single MPPT string."
    return {"status": status, "label": label, "detail": detail, "efficiency_pct": eff_pct, "load_pct": load_pct}


def pv_voltage_headroom(pv1_v: float) -> dict:
    """Assess how close PV string voltage is to the 550V absolute max."""
    if pv1_v < 10:
        return {"status": "no_data", "label": "No PV data", "voltage_v": 0, "pct_used": 0}
    pct_used = round(pv1_v / MAX_DC_VOLTAGE_V * 100, 1)
    if pv1_v > VOLTAGE_WARN_V:
        status = "warning"
        label  = f"{pv1_v:.0f}V — approaching 550V limit ({pct_used:.0f}% used)"
    elif pv1_v > VOLTAGE_CAUTION_V:
        status = "caution"
        label  = f"{pv1_v:.0f}V — elevated ({pct_used:.0f}% of 550V max)"
    else:
        status = "normal"
        label  = f"{pv1_v:.0f}V ({pct_used:.0f}% of 550V max)"
    return {"status": status, "label": label, "voltage_v": round(pv1_v, 1), "pct_used": pct_used}


def shading_signal(pv1_v: float, poa_wm2: float, hour_of_day: int) -> dict | None:
    """
    Detect possible single-string shading.
    On a clear mid-day, PV1 voltage should be stable near MPP (~250–310V for 6×595W).
    A significant dip in voltage without corresponding cloud cover suggests partial shading
    on one or more panels dragging down the entire single-MPPT string.
    Returns None if conditions aren't suitable for shading detection.
    """
    if poa_wm2 < 400 or hour_of_day < 9 or hour_of_day > 16:
        return None  # Too early/late or too cloudy to diagnose
    # 6 × Vikram HyperSol 595W: Vmpp ≈ 40.9V → string Vmpp ≈ 245V
    # Voc ≈ 49.6V → string Voc ≈ 298V
    EXPECTED_VMPP = 245.0
    if pv1_v < EXPECTED_VMPP * 0.80:  # >20% below expected MPP voltage
        drop_pct = round((EXPECTED_VMPP - pv1_v) / EXPECTED_VMPP * 100, 0)
        return {
            "detected": True,
            "pv1_voltage": round(pv1_v, 1),
            "expected_vmpp": EXPECTED_VMPP,
            "voltage_drop_pct": drop_pct,
            "detail": (
                f"PV1 voltage {pv1_v:.0f}V is {drop_pct:.0f}% below expected MPP (~{EXPECTED_VMPP:.0f}V) "
                f"at {poa_wm2:.0f} W/m² irradiance. "
                "Single-MPPT string: shading on any one panel drags all 6 down. "
                "Check for shadow from adjacent structures, dust streaks, or bird droppings on specific panels."
            ),
        }
    return {"detected": False}


def thermal_context(radiator_temp_c: float, ambient_temp_c: float) -> dict:
    """Explain thermal state relative to KSolar 5G-PRO+ operating limits."""
    if radiator_temp_c < 1:
        return {"status": "no_data", "label": "No data", "detail": None, "derating": False}
    derating = ambient_temp_c > AMBIENT_PEAK_C
    if radiator_temp_c > 80:
        status = "critical"
        label  = f"{radiator_temp_c:.0f}°C — F8 fault imminent"
        detail = "Inverter near thermal shutdown limit. Immediately check 300mm clearance on all sides and verify fan is running."
    elif radiator_temp_c > 65:
        status = "warning"
        label  = f"{radiator_temp_c:.0f}°C — elevated"
        detail = f"Ambient {ambient_temp_c:.0f}°C. Above 45°C ambient, inverter derates output to protect itself — generation reduced."
    elif radiator_temp_c > 50:
        status = "warm"
        label  = f"{radiator_temp_c:.0f}°C — warm, fan active"
        detail = f"Smart fan running. Ambient {ambient_temp_c:.0f}°C. Within normal operating range."
    else:
        status = "normal"
        label  = f"{radiator_temp_c:.0f}°C — cool"
        detail = "Passive cooling sufficient. No derating expected."
    return {"status": status, "label": label, "detail": detail, "derating": derating,
            "radiator_c": radiator_temp_c, "ambient_c": ambient_temp_c}
