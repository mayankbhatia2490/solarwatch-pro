from influxdb_client import InfluxDBClient
from config import settings

_client = None

def get_client() -> InfluxDBClient:
    global _client
    if _client is None:
        _client = InfluxDBClient(
            url=settings.influxdb_url,
            token=settings.influxdb_token,
            org=settings.influxdb_org
        )
    return _client

def query(flux: str) -> list:
    client = get_client()
    query_api = client.query_api()
    tables = query_api.query(flux, org=settings.influxdb_org)
    results = []
    for table in tables:
        for record in table.records:
            results.append(record)
    return results

def query_to_dicts(flux: str) -> list[dict]:
    records = query(flux)
    return [{"time": r.get_time(), "field": r.get_field(), "value": r.get_value()} for r in records]
