import os
import time
import hashlib
import json
import logging
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime, timedelta
import requests
import schedule
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS
import urllib.parse
import ai_analyst

# --- Configuration ---
# ShineMonitor
USERNAME = os.environ.get('SHINEMONITOR_USERNAME')
PASSWORD = os.environ.get('SHINEMONITOR_PASSWORD')
COMPANY_KEY = os.environ.get('SHINEMONITOR_COMPANY_KEY', '') 
PLANT_ID = os.environ.get('SHINEMONITOR_PLANT_ID', '')
PN = os.environ.get('SHINEMONITOR_PN', '')
SN = os.environ.get('SHINEMONITOR_SN', '')
DEVCODE = os.environ.get('SHINEMONITOR_DEVCODE', '1')
BASE_URL = 'http://web.shinemonitor.com/public/'
TOKEN_FILE = '/app/data/token.json'
HEARTBEAT_FILE = '/app/data/heartbeat.txt'

# Open-Meteo
LATITUDE = os.environ.get('LATITUDE', '29.6857')
LONGITUDE = os.environ.get('LONGITUDE', '76.9905')
TIMEZONE = os.environ.get('TIMEZONE', 'Asia/Kolkata')

# InfluxDB
INFLUX_URL = os.environ.get('INFLUXDB_URL', 'http://influxdb:8086')
INFLUX_TOKEN = os.environ.get('INFLUXDB_TOKEN', '')
INFLUX_ORG = os.environ.get('INFLUXDB_ORG', 'solar')
INFLUX_BUCKET = os.environ.get('INFLUXDB_BUCKET', 'solar_metrics')

# SMTP Email
SMTP_SERVER = os.environ.get('SMTP_SERVER')
SMTP_PORT = int(os.environ.get('SMTP_PORT', '587'))
SMTP_USERNAME = os.environ.get('SMTP_USERNAME')
SMTP_PASSWORD = os.environ.get('SMTP_PASSWORD')
EMAIL_FROM = os.environ.get('EMAIL_FROM')
EMAIL_TO = os.environ.get('EMAIL_TO')

# Capacity
INSTALLED_CAPACITY_W = float(os.environ.get('INSTALLED_CAPACITY_W', '3500'))

# Alerting State
ALARM_STATE = {
    "offline_count": 0,
    "avoidable_loss_count": 0,
    "last_email_sent": None
}

# Gemini (AI Analysis)
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')

# Logging setup
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Wait for InfluxDB to start up
time.sleep(10)
try:
    influx_client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
    write_api = influx_client.write_api(write_options=SYNCHRONOUS)
    logger.info("Connected to InfluxDB")
except Exception as e:
    logger.error(f"Failed to connect to InfluxDB: {e}")

# --- Email Logic ---
def send_email_alert(subject, body):
    if not SMTP_SERVER or not SMTP_USERNAME or not SMTP_PASSWORD:
        logger.warning(f"Email not configured. Would have sent: {subject}")
        return
        
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_FROM
        msg['To'] = EMAIL_TO
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))
        
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(SMTP_USERNAME, SMTP_PASSWORD)
        server.send_message(msg)
        server.quit()
        logger.info(f"Email alert sent: {subject}")
    except Exception as e:
        logger.error(f"Failed to send email alert: {e}")

def check_alarms(solar, weather, avoidable_loss):
    global ALARM_STATE
    current_time = datetime.now()
    
    # Send email max once every 2 hours to avoid spam
    if ALARM_STATE["last_email_sent"]:
        if (current_time - ALARM_STATE["last_email_sent"]).total_seconds() < 7200:
            return

    alarms = []
    
    # 1. Device Offline
    if solar['status_code'] == 1: # 1 = Offline
        ALARM_STATE["offline_count"] += 1
        if ALARM_STATE["offline_count"] >= 3: # Offline for 15 mins
            alarms.append("CRITICAL: Your Datalogger (PN: I30000250375210605) is Offline.")
    else:
        ALARM_STATE["offline_count"] = 0
        
    # 2. Avoidable Loss
    if avoidable_loss == 1:
        ALARM_STATE["avoidable_loss_count"] += 1
        if ALARM_STATE["avoidable_loss_count"] >= 4: # Loss persists for 20 mins
            alarms.append(f"WARNING: Solar production is significantly lower than expected!\n"
                          f"Current Power: {solar['power_now_w']}W\n"
                          f"Solar Radiation: {weather['shortwave_radiation_wm2']} W/m2\n"
                          f"Cloud Cover: {weather['cloud_cover_pct']}%\n"
                          f"Recommendation: Please inspect panels for heavy dust, shading, or check the inverter.")
    else:
        ALARM_STATE["avoidable_loss_count"] = 0

    if alarms:
        subject = "[Solar Monitor] " + alarms[0].split(':')[0]
        body = "\n\n".join(alarms)
        send_email_alert(subject, body)
        ALARM_STATE["last_email_sent"] = current_time

# --- ShineMonitor Auth Logic ---
def get_salt():
    return int(round(time.time() * 1000))

def request_token():
    logger.info("Requesting new ShineMonitor token...")
    salt = get_salt()
    powSha1 = hashlib.sha1()
    powSha1.update(PASSWORD.encode('utf-8'))
    
    # The action string needs to exactly match the signed version
    # The username must be URL-encoded in the action string for the signature to match the server side
    encoded_usr = urllib.parse.quote(USERNAME)
    action = f'&action=auth&usr={encoded_usr}&company-key={COMPANY_KEY}'
    pwdaction = str(salt) + str(powSha1.hexdigest()) + action
    
    auth_sign = hashlib.sha1()
    auth_sign.update(pwdaction.encode('utf-8'))
    sign = str(auth_sign.hexdigest())
    
    auth_url = f"{BASE_URL}?sign={sign}&salt={salt}{action}"
    
    try:
        r = requests.get(auth_url, timeout=15)
        data = r.json()
        if data.get('err') == 0:
            token_data = data['dat']
            expire_seconds = token_data['expire']
            expire_dt = datetime.now() + timedelta(seconds=expire_seconds)
            token_data['expire_time'] = expire_dt.isoformat()
            
            # Save token
            os.makedirs(os.path.dirname(TOKEN_FILE), exist_ok=True)
            with open(TOKEN_FILE, 'w') as f:
                json.dump(token_data, f)
            logger.info("New token acquired and saved.")
            return token_data
        else:
            logger.error(f"Auth failed: {data}")
            return None
    except Exception as e:
        logger.error(f"Auth request exception: {e}")
        return None

def get_token():
    try:
        if os.path.exists(TOKEN_FILE):
            with open(TOKEN_FILE, 'r') as f:
                token_data = json.load(f)
            expire_time = datetime.fromisoformat(token_data['expire_time'])
            if datetime.now() < expire_time:
                return token_data
    except Exception as e:
        logger.warning(f"Could not read existing token: {e}")
    
    return request_token()

def build_request_url(action_params):
    token_data = get_token()
    if not token_data:
        return None
        
    salt = get_salt()
    secret = token_data['secret']
    token = token_data['token']
    
    reqaction = str(salt) + secret + token + action_params
    req_sign = hashlib.sha1()
    req_sign.update(reqaction.encode('utf-8'))
    sign = str(req_sign.hexdigest())
    
    return f"{BASE_URL}?sign={sign}&salt={salt}&token={token}{action_params}"

# --- Data Fetching ---
def fetch_shinemonitor_data():
    logger.info("Fetching ShineMonitor data...")
    # 1. Fetch current power & daily energy
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
            logger.error(f"Error fetching energy data: {e}")

    # 2. Fetch Status
    status_params = f"&action=queryPlantDeviceDesignatedInformation&plantid={PLANT_ID}&devtype=512"
    status_url = build_request_url(status_params)
    device_status = 1 # 1 = Offline, 0 = Online default
    
    if status_url:
        try:
            r = requests.get(status_url, timeout=15)
            data = r.json()
            if data.get('err') == 0 and 'device' in data['dat'] and len(data['dat']['device']) > 0:
                device_status = data['dat']['device'][0]['status']
        except Exception as e:
            logger.error(f"Error fetching status data: {e}")

    # 3. Fetch Summary
    summary_params = f"&action=queryPlantCurrentData&plantid={PLANT_ID}&par=ENERGY_TODAY,ENERGY_MONTH,ENERGY_YEAR,ENERGY_TOTAL"
    summary_url = build_request_url(summary_params)
    total_energy = 0.0
    if summary_url:
        try:
            r = requests.get(summary_url, timeout=15)
            data = r.json()
            if data.get('err') == 0:
                daily_energy = float(data['dat'][0]['val'])
                total_energy = float(data['dat'][3]['val'])
        except Exception as e:
             logger.error(f"Error fetching summary data: {e}")

    return {
        "power_now_w": power_now,
        "daily_energy_kwh": daily_energy,
        "total_energy_kwh": total_energy,
        "status_code": device_status,
        "extra_metrics": extra_metrics
    }

def fetch_weather_data():
    logger.info("Fetching Open-Meteo data...")
    url = f"https://api.open-meteo.com/v1/forecast?latitude={LATITUDE}&longitude={LONGITUDE}&current=temperature_2m,precipitation,cloud_cover,shortwave_radiation,wind_speed_10m&timezone={TIMEZONE}"
    try:
        r = requests.get(url, timeout=15)
        data = r.json()
        current = data.get('current', {})
        return {
            "temperature_c": current.get('temperature_2m', 0),
            "cloud_cover_pct": current.get('cloud_cover', 0),
            "shortwave_radiation_wm2": current.get('shortwave_radiation', 0),
            "precipitation_mm": current.get('precipitation', 0),
            "wind_speed_kmh": current.get('wind_speed_10m', 0)
        }
    except Exception as e:
        logger.error(f"Error fetching weather data: {e}")
        return {
            "temperature_c": 0, "cloud_cover_pct": 0, "shortwave_radiation_wm2": 0,
            "precipitation_mm": 0, "wind_speed_kmh": 0
        }

# --- Main Logic ---
def job():
    try:
        # Touch heartbeat file for Docker healthcheck
        os.makedirs(os.path.dirname(HEARTBEAT_FILE), exist_ok=True)
        with open(HEARTBEAT_FILE, 'w') as f:
            f.write(str(time.time()))

        solar = fetch_shinemonitor_data()
        weather = fetch_weather_data()
        
        # Calculate Expected Power (basic model: Capacity * Radiation / 1000 * derating)
        # Assuming 75% efficiency overall (temperature, dust, inverter)
        derating_factor = 0.75
        expected_power_w = INSTALLED_CAPACITY_W * (weather['shortwave_radiation_wm2'] / 1000.0) * derating_factor
        
        # Avoidable Loss Logic
        # If radiation is high (> 300), clouds are low (< 50%), and actual power is less than 50% of expected
        avoidable_loss = 0
        if weather['shortwave_radiation_wm2'] > 300 and weather['cloud_cover_pct'] < 50:
            if solar['power_now_w'] < (expected_power_w * 0.5):
                avoidable_loss = 1
                
        # Check alarms and send emails if needed
        check_alarms(solar, weather, avoidable_loss)
        
        # Real-time AI event detection (no Gemini call unless anomaly found)
        ai_analyst.check_realtime_events(solar, weather, send_email_alert)
        
        # Write to InfluxDB
        point = Point("solar_metrics") \
            .field("power_now_w", float(solar['power_now_w'])) \
            .field("daily_energy_kwh", float(solar['daily_energy_kwh'])) \
            .field("total_energy_kwh", float(solar['total_energy_kwh'])) \
            .field("status_code", int(solar['status_code'])) \
            .field("temperature_c", float(weather['temperature_c'])) \
            .field("cloud_cover_pct", float(weather['cloud_cover_pct'])) \
            .field("shortwave_radiation_wm2", float(weather['shortwave_radiation_wm2'])) \
            .field("precipitation_mm", float(weather['precipitation_mm'])) \
            .field("wind_speed_kmh", float(weather['wind_speed_kmh'])) \
            .field("expected_power_w", float(expected_power_w)) \
            .field("avoidable_loss_flag", int(avoidable_loss))
            
        for k, v in solar.get("extra_metrics", {}).items():
            point = point.field(k, float(v))
            
        write_api.write(bucket=INFLUX_BUCKET, record=point)
        logger.info(f"Data written to InfluxDB: Power={solar['power_now_w']}W, Rad={weather['shortwave_radiation_wm2']}W/m2")
        
    except Exception as e:
        logger.error(f"Job failed: {e}")

if __name__ == "__main__":
    logger.info("Solar Collector starting up...")
    # Run once immediately
    job()
    # Schedule every 5 minutes
    schedule.every(5).minutes.do(job)
    # Daily AI report at 7:00 AM — only 1 Gemini call per day
    schedule.every().day.at("07:00").do(
        lambda: ai_analyst.send_daily_ai_report(send_email_alert)
    )
    
    while True:
        schedule.run_pending()
        time.sleep(1)
