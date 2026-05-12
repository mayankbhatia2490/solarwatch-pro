from contextvars import ContextVar
from influxdb_client import InfluxDBClient
from config import settings

_client = None

# Per-request site_id — set by middleware, consumed by query()
_site_id_var: ContextVar[str] = ContextVar("site_id", default="")

def set_request_site_id(site_id: str) -> None:
    _site_id_var.set(site_id)

def get_request_site_id() -> str:
    return _site_id_var.get()

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
    site_id = _site_id_var.get()
    if site_id and site_id != "default":
        # Inject site_id tag filter at end of pipeline — works for all Flux queries
        # since tags survive every transformation step.
        flux = flux.rstrip() + f'\n  |> filter(fn: (r) => r["site_id"] == "{site_id}")'
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
