import requests

url = 'http://localhost:8086/api/v2/query?org=solar'
headers = {
    'Authorization': 'Token -GigT89uoG_SurDkZPrgLuCRiDz1_y5StephYpyKsn1SBvwKqcCP9EhT5Cmwofc0v8LEOh51M-8Q8VTDNEmOXA==',
    'Content-type': 'application/vnd.flux'
}
data = 'from(bucket:"solar_metrics") |> range(start: -1m)'

r = requests.post(url, headers=headers, data=data)
print(r.status_code, r.text)
