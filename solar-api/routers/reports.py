from fastapi import APIRouter
from typing import Dict, Any
from datetime import datetime, timezone

router = APIRouter(prefix="/api/reports", tags=["Reports"])

@router.get("/")
def get_available_reports() -> Dict[str, Any]:
    """
    Returns a list of generated reports and configuration options.
    """
    return {
        "status": "success",
        "data": {
            "configurations": {
                "daily_telegram": True,
                "weekly_summary": True,
                "monthly_detailed": True,
                "ai_insights_enabled": True
            },
            "recent_reports": [
                {
                    "id": "rep-001",
                    "date": datetime.now(timezone.utc).isoformat(),
                    "type": "Daily AI Summary",
                    "destination": "Telegram",
                    "status": "Delivered"
                },
                {
                    "id": "rep-002",
                    "date": "2026-05-01T00:00:00Z",
                    "type": "Monthly Performance PDF",
                    "destination": "Email",
                    "status": "Delivered"
                }
            ]
        }
    }

@router.post("/generate")
def trigger_report_generation(report_type: str = "daily") -> Dict[str, Any]:
    """
    Manually triggers a report generation.
    """
    # In production, this would trigger a Celery/Background task to compile the report
    return {
        "status": "success",
        "message": f"{report_type.capitalize()} report generation triggered. It will be sent via configured channels."
    }
