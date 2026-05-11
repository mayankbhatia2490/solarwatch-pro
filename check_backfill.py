import requests
from datetime import datetime

url = 'http://localhost:8086/api/v2/query?org=solar'
headers = {
    'Authorization': 'Token -GigT89uoG_SurDkZPrgLuCRiDz1_y5StephYpyKsn1SBvwKqcCP9EhT5Cmwofc0v8LEOh51M-8Q8VTDNEmOXA==',
    'Content-type': 'application/vnd.flux'
}

# Count unique days of data
flux = '''
from(bucket:"solar_metrics")
  |> range(start: 2025-04-01T00:00:00Z)
  |> filter(fn: (r) => r["_field"] == "power_now_w")
  |> aggregateWindow(every: 1d, fn: count, createEmpty: false)
  |> count()
'''

r = requests.post(url, headers=headers, data=flux)
print("Days of historical data:", r.text)
