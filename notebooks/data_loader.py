"""
data_loader.py — shared helper for all SolarWatch Pro notebooks.
Loads data from InfluxDB and enriches with Open-Meteo historical weather.
Usage: df = load_solar_data()
"""
import os, json, urllib.request
import pandas as pd
import numpy as np
from influxdb_client import InfluxDBClient

LAT, LON = 29.693405600010355, 76.99938211551195
INSTALL_DATE = "2025-04-17"

def load_solar_data(start=f"{INSTALL_DATE}T00:00:00Z"):
    INFLUX_URL   = os.environ.get("INFLUXDB_URL",    "http://influxdb:8086")
    INFLUX_TOKEN = os.environ.get("INFLUXDB_TOKEN",  "")
    INFLUX_ORG   = os.environ.get("INFLUXDB_ORG",    "solar")
    BUCKET       = os.environ.get("INFLUXDB_BUCKET", "solar_metrics")

    client    = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
    query_api = client.query_api()

    flux = f'''
from(bucket: "{BUCKET}")
  |> range(start: {start})
  |> filter(fn: (r) =>
      r["_field"] == "power_now_w"                  or
      r["_field"] == "pv1_voltage"                  or
      r["_field"] == "pv1_current"                  or
      r["_field"] == "shortwave_radiation_wm2"      or
      r["_field"] == "internal_ambient_temperature" or
      r["_field"] == "internal_radiator_temperature" or
      r["_field"] == "daily_energy_kwh")
  |> aggregateWindow(every: 15m, fn: mean, createEmpty: false)
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
  |> sort(columns: ["_time"])
'''
    tables = query_api.query_data_frame(flux)
    df = pd.concat(tables, ignore_index=True) if isinstance(tables, list) else tables
    client.close()

    df = df.rename(columns={"_time": "datetime"})
    df["datetime"] = pd.to_datetime(df["datetime"], utc=True).dt.tz_convert("Asia/Kolkata")
    df = df.sort_values("datetime").reset_index(drop=True)

    # DC power from voltage × current
    df["dc_power"] = df.get("pv1_voltage", pd.Series(0, index=df.index)).fillna(0) * \
                     df.get("pv1_current", pd.Series(0, index=df.index)).fillna(0)

    # Drop nighttime (zero output rows add noise to ML)
    df = df[df["power_now_w"].fillna(0) > 0].copy()

    # Time features
    df["hour"]        = df["datetime"].dt.hour
    df["month"]       = df["datetime"].dt.month
    df["month_name"]  = df["datetime"].dt.strftime("%b")
    df["day_of_year"] = df["datetime"].dt.day_of_year
    df["date"]        = df["datetime"].dt.date

    # Fetch historical irradiance & temperature from Open-Meteo archive API
    try:
        s = df["datetime"].min().strftime("%Y-%m-%d")
        e = df["datetime"].max().strftime("%Y-%m-%d")
        url = (f"https://archive-api.open-meteo.com/v1/archive"
               f"?latitude={LAT}&longitude={LON}"
               f"&start_date={s}&end_date={e}"
               f"&hourly=shortwave_radiation,direct_radiation,temperature_2m"
               f"&timezone=Asia%2FKolkata")
        with urllib.request.urlopen(url, timeout=30) as resp:
            wx = json.loads(resp.read())
        wx_df = pd.DataFrame({
            "datetime_h":    pd.to_datetime(wx["hourly"]["time"]).tz_localize("Asia/Kolkata"),
            "irr_hist":      wx["hourly"]["shortwave_radiation"],
            "direct_hist":   wx["hourly"]["direct_radiation"],
            "temp_hist":     wx["hourly"]["temperature_2m"],
        })
        df["datetime_h"] = df["datetime"].dt.floor("h")
        df = df.merge(wx_df, on="datetime_h", how="left")
        df["irradiance"]   = df["shortwave_radiation_wm2"].fillna(df["irr_hist"])
        df["ambient_temp"] = df["internal_ambient_temperature"].fillna(df["temp_hist"])
        print(f"✅ Open-Meteo archive fetched  |  irradiance coverage: {df['irradiance'].notna().mean()*100:.1f}%")
    except Exception as exc:
        print(f"⚠️  Open-Meteo fetch failed: {exc}")
        df["irradiance"]   = df.get("shortwave_radiation_wm2", pd.Series(dtype=float))
        df["ambient_temp"] = df.get("internal_ambient_temperature", pd.Series(dtype=float))

    # Fill residual NaNs with per-hour medians so ML has no gaps
    for col in ["irradiance", "ambient_temp"]:
        df[col] = df[col].fillna(df.groupby("hour")[col].transform("median"))

    df["module_temp"] = df.get("internal_radiator_temperature",
                               pd.Series(dtype=float)).fillna(df["ambient_temp"] + 8)

    print(f"✅ {len(df):,} daytime rows  |  "
          f"{df['datetime'].min().date()} → {df['datetime'].max().date()}")
    return df
