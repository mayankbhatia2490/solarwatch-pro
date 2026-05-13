import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from routers import (
    dashboard, electrical, notifications, grid, thermal,
    anomalies, maintenance, performance, weather, reports,
    settings as settings_router, forecast, cleaning, sites, fleet, export, analysis,
)
from influx import set_request_site_id
from config import settings
import monitor

@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(monitor.run_monitor())
    yield
    task.cancel()

app = FastAPI(
    title="SolarWatch Pro API",
    version="1.0.0",
    description="Solar monitoring REST API — reads from InfluxDB",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def site_id_middleware(request: Request, call_next):
    """Extract X-Site-ID header and make it available to all Flux queries."""
    site_id = request.headers.get("X-Site-ID", settings.site_id)
    set_request_site_id(site_id)
    response = await call_next(request)
    return response

app.include_router(dashboard.router,         prefix="/api/dashboard",      tags=["Dashboard"])
app.include_router(electrical.router,        prefix="/api/electrical",     tags=["Electrical"])
app.include_router(notifications.router,     prefix="/api/notifications",  tags=["Notifications"])
app.include_router(settings_router.router,   prefix="/api/settings",       tags=["Settings"])
app.include_router(grid.router)
app.include_router(thermal.router)
app.include_router(anomalies.router)
app.include_router(maintenance.router)
app.include_router(performance.router)
app.include_router(weather.router)
app.include_router(reports.router)
app.include_router(forecast.router)
app.include_router(cleaning.router)
app.include_router(sites.router)
app.include_router(fleet.router)
app.include_router(export.router)
app.include_router(analysis.router)

@app.get("/health")
async def health():
    return {"status": "ok", "service": "SolarWatch Pro API"}
