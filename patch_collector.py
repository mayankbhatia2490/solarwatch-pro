import re

with open(r'c:\Users\mayan\Documents\Antigravity\solar-monitoring-stack\collector\solar_collector.py', 'r') as f:
    code = f.read()

new_fetch_energy = """    # 1. Fetch current power & daily energy
    date_str = datetime.today().strftime('%Y-%m-%d')
    energy_params = f"&action=queryDeviceDataOneDayPaging&devaddr=1&pn={PN}&devcode={DEVCODE}&sn={SN}&date={date_str}"
    
    energy_url = build_request_url(energy_params)
    power_now = 0.0
    daily_energy = 0.0
    extra_metrics = {}
    
    if energy_url:
        try:
            r = requests.get(energy_url, timeout=15)
            data = r.json()
            if data.get('err') == 0 and 'title' in data['dat'] and 'row' in data['dat'] and len(data['dat']['row']) > 0:
                titles = [t['title'] for t in data['dat']['title']]
                row = data['dat']['row'][0]['field']
                
                # Dynamic extraction based on title names
                for i, title in enumerate(titles):
                    if i < len(row):
                        try:
                            val = float(row[i])
                            if title == 'Output Power': power_now = val
                            elif title == 'Energy today': daily_energy = val
                            # Capture other important electrical parameters
                            elif title in ['PV1 voltage', 'PV1 current', 'PV2 voltage', 'PV2 current', 
                                         'Grid R voltage', 'Grid R current', 'Grid S voltage', 'Grid S current',
                                         'Grid T voltage', 'Grid T current',
                                         'Grid frequency', 'bus voltage',
                                         'Internal ambient temperature', 'Internal radiator temperature']:
                                extra_metrics[title.lower().replace(' ', '_')] = val
                        except ValueError:
                            pass # string values like 'Normal' status
        except Exception as e:
            logger.error(f"Error fetching energy data: {e}")"""

# Replace the old section
old_fetch = """    # 1. Fetch current power & daily energy
    date_str = datetime.today().strftime('%Y-%m-%d')
    energy_params = f"&action=queryDeviceDataOneDayPaging&devaddr=1&pn={PN}&devcode={DEVCODE}&sn={SN}&date={date_str}"
    
    energy_url = build_request_url(energy_params)
    power_now = 0.0
    daily_energy = 0.0
    
    if energy_url:
        try:
            r = requests.get(energy_url, timeout=15)
            data = r.json()
            if data.get('err') == 0 and 'row' in data['dat'] and len(data['dat']['row']) > 0:
                # Based on reverse engineered API, field[5] is often current power
                row = data['dat']['row'][0]
                power_now = float(row['field'][5] if len(row['field']) > 5 else 0)
        except Exception as e:
            logger.error(f"Error fetching energy data: {e}")"""

code = code.replace(old_fetch, new_fetch_energy)

# Update return dict
code = code.replace("""    return {
        "power_now_w": power_now,
        "daily_energy_kwh": daily_energy,
        "total_energy_kwh": total_energy,
        "status_code": device_status
    }""", """    return {
        "power_now_w": power_now,
        "daily_energy_kwh": daily_energy,
        "total_energy_kwh": total_energy,
        "status_code": device_status,
        "extra_metrics": extra_metrics
    }""")

# Update influxdb write
old_write = """        # Write to InfluxDB
        point = Point("solar_metrics") \\
            .field("power_now_w", float(solar['power_now_w'])) \\
            .field("daily_energy_kwh", float(solar['daily_energy_kwh'])) \\
            .field("total_energy_kwh", float(solar['total_energy_kwh'])) \\
            .field("status_code", int(solar['status_code'])) \\
            .field("temperature_c", float(weather['temperature_c'])) \\
            .field("cloud_cover_pct", float(weather['cloud_cover_pct'])) \\
            .field("shortwave_radiation_wm2", float(weather['shortwave_radiation_wm2'])) \\
            .field("precipitation_mm", float(weather['precipitation_mm'])) \\
            .field("wind_speed_kmh", float(weather['wind_speed_kmh'])) \\
            .field("expected_power_w", float(expected_power_w)) \\
            .field("avoidable_loss_flag", int(avoidable_loss))"""

new_write = """        # Write to InfluxDB
        point = Point("solar_metrics") \\
            .field("power_now_w", float(solar['power_now_w'])) \\
            .field("daily_energy_kwh", float(solar['daily_energy_kwh'])) \\
            .field("total_energy_kwh", float(solar['total_energy_kwh'])) \\
            .field("status_code", int(solar['status_code'])) \\
            .field("temperature_c", float(weather['temperature_c'])) \\
            .field("cloud_cover_pct", float(weather['cloud_cover_pct'])) \\
            .field("shortwave_radiation_wm2", float(weather['shortwave_radiation_wm2'])) \\
            .field("precipitation_mm", float(weather['precipitation_mm'])) \\
            .field("wind_speed_kmh", float(weather['wind_speed_kmh'])) \\
            .field("expected_power_w", float(expected_power_w)) \\
            .field("avoidable_loss_flag", int(avoidable_loss))
            
        for k, v in solar.get("extra_metrics", {}).items():
            point = point.field(k, float(v))"""

code = code.replace(old_write, new_write)

with open(r'c:\Users\mayan\Documents\Antigravity\solar-monitoring-stack\collector\solar_collector.py', 'w') as f:
    f.write(code)
print('Patched successfully')
