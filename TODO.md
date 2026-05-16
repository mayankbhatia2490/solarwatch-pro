# SolarWatch Pro — Feature Backlog

## High Priority

### Clear-Sky Performance Baseline
- Replace Open-Meteo expected power with a clear-sky model (purely astronomical, no weather API)
- Clear-sky max = theoretical irradiance given sun position × panel geometry × system constants
- Actual ÷ clear-sky max = weather-independent efficiency score (removes irradiance source uncertainty)
- Filter analysis to show PR separately for clear days (cloud_cover < 10%) vs cloudy days
- This eliminates the Open-Meteo winter overestimation problem entirely

### PVGIS Irradiance Cross-Validation
- Fetch monthly GHI from PVGIS API (EU JRC, SARAH-3 dataset — gold standard for India)
- URL: `https://re.jrc.ec.europa.eu/api/v5_2/MRcalc?lat=29.69&lon=76.99&outputformat=json`
- Compare PVGIS vs VEDAS vs Open-Meteo for Karnal monthly values
- Use whichever source best matches actual InfluxDB production as the reference
- Add to tilt-analysis.html as a 4th data series

## Medium Priority

### UHBVN Meter Reading Entry (Manual — most reliable)
- Add a "Monthly Meter Reading" page under Maintenance
- Fields: reading date, export units (from UHBVN meter), bill amount (₹), meter reading value
- Store in InfluxDB as `uhbvn_readings` measurement
- Auto-calculate:
  - Self-consumed units = InfluxDB generation − export units
  - Self-consumption ratio %
  - Actual savings vs estimated savings (validate tariff assumptions)
  - Cross-check InfluxDB generation accuracy against billing meter
- Why not auto-scrape UHBVN portal: no public API, scraping is fragile, credential storage is a security risk

### UHBVN PDF Bill Parser (Optional enhancement to above)
- If UHBVN sends PDF bills by email, watch a folder or email inbox
- Use pdfplumber to extract: billing period, export units, amount, meter number
- Auto-populate the meter reading entry above
- Only worth building if manual entry feels too tedious after a few months

## Low Priority / Research

### Pyranometer Integration
- A physical irradiance sensor (₹5,000–15,000) would give ground-truth GHI on-site
- Even a cheap BH1750 lux sensor (₹200) can be calibrated to give approximate GHI
- Would make the expected power calculation 100% accurate
- Connect via ESP32/Raspberry Pi → MQTT → InfluxDB (same pipeline as collector)

### KSolar Inverter Data Cross-Check
- The KSolar inverter has its own cloud portal (see existing scrape_login.py)
- Compare inverter portal lifetime kWh vs InfluxDB total — should match within 1%
- If there's drift, CT clamp calibration may be off
