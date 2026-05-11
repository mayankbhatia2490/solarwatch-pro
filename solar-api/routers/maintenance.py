from fastapi import APIRouter
from typing import Dict, Any
from datetime import datetime, timezone, timedelta
import random

router = APIRouter(prefix="/api/maintenance", tags=["Maintenance"])

@router.get("/")
def get_maintenance_status() -> Dict[str, Any]:
    """
    Returns predictive maintenance heuristics and upcoming schedule.
    In a full production environment, this would train on historical PR degradation.
    """
    now = datetime.now(timezone.utc)
    
    # Static logic based on the user's specific install date (17 April 2025)
    install_date = datetime(2025, 4, 17, tzinfo=timezone.utc)
    days_installed = (now - install_date).days
    
    # Let's say standard cleaning is every 60 days
    days_since_clean = days_installed % 60
    days_to_next_clean = 60 - days_since_clean
    next_clean_date = now + timedelta(days=days_to_next_clean)
    
    # Let's say standard inverter check is 365 days
    days_to_annual = 365 - (days_installed % 365)
    
    predictions = [
        {
            "id": "pred-1",
            "title": "Panel Soiling Detected",
            "trend": "String 1 & 2 voltage dropping 2% faster than expected over 30 days.",
            "impact_week_4": "Estimated 8% output loss",
            "urgency": "medium",
            "confidence": 85,
            "fix_cost_inr": 500,
            "revenue_saved_inr": 1200,
            "action": "Schedule panel cleaning"
        },
        {
            "id": "pred-2",
            "title": "Radiator Fan Wear",
            "trend": "Peak temperature reaching 75°C consistently during peak hours.",
            "impact_week_4": "Derating limit hit; 5% total energy loss",
            "urgency": "low",
            "confidence": 62,
            "fix_cost_inr": 1500,
            "revenue_saved_inr": 800,
            "action": "Check inverter fan/filter"
        }
    ]

    history = [
        {"date": (now - timedelta(days=days_since_clean)).isoformat(), "action": "Manual Panel Cleaning", "outcome": "Output increased by 6%"},
        {"date": install_date.isoformat(), "action": "System Installation", "outcome": "Commissioning successful"}
    ]

    return {
        "status": "success", 
        "data": {
            "next_service_date": next_clean_date.isoformat(),
            "next_service_type": "Routine Cleaning",
            "days_to_service": days_to_next_clean,
            "predictions": predictions,
            "history": history
        }
    }
