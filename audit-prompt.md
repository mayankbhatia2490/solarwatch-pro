# SolarWatch Pro — Data Integrity Audit Prompt

Paste the prompt below into Claude Code (or run as a slash command) anytime
you want to re-audit the app. The goal is to catch:

- Fabricated fallback data shown as if it were real
- Wrong formulas or unit mismatches
- Energy reconstructed from power samples (the 70 vs 129.6 kWh bug class)
- Hardcoded assumptions not flagged as such
- Numbers that can't be traced to a real InfluxDB field

---

You are auditing SolarWatch Pro for data integrity. Be ruthless — assume
every number is fabricated until proven otherwise. Do not write code,
do not fix anything — produce a report only.

For every endpoint under solar-api/routers/* and every card/value
displayed in solar-frontend/, answer these questions:

1. SOURCE OF TRUTH
   - Which InfluxDB field is each displayed number derived from?
   - Is that field written by the collector from a real measurement
     (Shinemonitor API, CT clamp, Open-Meteo) or computed from assumptions?
   - For any computed value, list every constant used (PR, BIFACIAL, NOCT,
     temp coefficient, etc.) and whether it's measured, assumed, or
     hardcoded from a datasheet.

2. FORMULA CORRECTNESS
   - For each calculation, name the industry-standard formula it implements
     (e.g., IEC 61724 Performance Ratio, Liu-Jordan tilt factor, NOCT
     temperature correction).
   - Flag any formula that deviates from the standard or invents its own.
   - Check units rigorously: W vs Wh, kWh vs MJ, GHI vs POA, percent vs
     fraction. Catch every unit mismatch.

3. ENERGY ACCOUNTING BUGS
   - Anywhere energy (kWh) is reconstructed from power samples (W),
     flag it as unreliable — the inverter's own cumulative counter
     (daily_energy_kwh, total_energy_kwh) is always the correct source.
   - Find every flux query that uses aggregateWindow + mean on power
     and treats the result as energy. List them.

4. FALLBACK & SYNTHETIC DATA
   - Find every hardcoded fallback (e.g., temperature=35, cloud_cover=15,
     fallback_poa=850) that gets shown when an API fails.
   - Flag any place that fabricates data instead of returning
     "unavailable" / null / empty.

5. CROSS-VALIDATION
   - For each displayed total (daily / weekly / monthly / yearly kWh,
     ₹ savings, CO₂), state how to verify it against an independent
     source: Shinemonitor portal, UHBVN bill, KSolar inverter display.
   - List the top 5 places most likely to disagree with Shinemonitor
     and why.

6. CALIBRATION DEPENDENCIES
   - Where is the PR=0.83 / bifacial=1.09 assumption used?
   - Is the irradiance_cal.json correction factor applied everywhere
     that uses expected_power, or only in some places?

Output format: one numbered table per section. Use file:line references.
No code changes. No diplomacy — if a number is wrong or suspicious,
say so plainly.
