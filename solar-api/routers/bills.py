"""
UHBVN Electricity Bill Upload & Parse — POST /api/bills/upload
Accepts a PDF bill, extracts text with pdfplumber, sends to Gemini for
structured extraction, stores confirmed data in InfluxDB.
"""
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from typing import Dict, Any
from datetime import datetime, timezone
import io
import json
import httpx

from config import settings
from influx import get_client

router = APIRouter(prefix="/api/bills", tags=["Bills"])

BUCKET = settings.influxdb_bucket

EXTRACT_PROMPT = """
You are parsing an Indian electricity bill from UHBVN (Uttar Haryana Bijli Vitran Nigam).
Extract the following fields from the bill text below.
Return ONLY a valid JSON object with these exact keys (use null if not found):

{
  "consumer_number": "string — consumer/account number",
  "meter_number": "string — meter serial number",
  "billing_period_from": "YYYY-MM-DD — start of billing period",
  "billing_period_to": "YYYY-MM-DD — end of billing period",
  "previous_reading_kwh": number — previous meter reading in kWh,
  "current_reading_kwh": number — current meter reading in kWh,
  "units_consumed_kwh": number — total units consumed (import from grid),
  "units_exported_kwh": number — net metering export units (solar export), null if not on net metering,
  "net_units_billed_kwh": number — net units billed after netting export,
  "amount_before_tax_inr": number — amount before taxes/surcharges,
  "total_amount_inr": number — total payable amount in rupees,
  "due_date": "YYYY-MM-DD",
  "tariff_category": "string — e.g. DS, NDS, industrial etc"
}

Bill text:
"""


async def _call_gemini(prompt: str, text: str) -> dict:
    """Call Gemini API to parse bill text into structured JSON."""
    api_key = settings.gemini_api_key
    if not api_key:
        raise HTTPException(status_code=503, detail="GEMINI_API_KEY not configured")

    full_prompt = prompt + text[:8000]  # cap at 8k chars

    # Try Gemini 2.5 Flash first, fall back to 1.5 Flash
    for model in ["gemini-2.5-flash", "gemini-1.5-flash", "gemini-1.5-flash-latest"]:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={api_key}"
        )
        payload = {
            "contents": [{"parts": [{"text": full_prompt}]}],
            "generationConfig": {"temperature": 0.1, "maxOutputTokens": 1024},
        }
        try:
            async with httpx.AsyncClient(timeout=20.0) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 404:
                    continue
                resp.raise_for_status()
                data = resp.json()
                raw = data["candidates"][0]["content"]["parts"][0]["text"]
                # Strip markdown code fences if present
                raw = raw.strip()
                if raw.startswith("```"):
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                return json.loads(raw.strip())
        except (json.JSONDecodeError, KeyError, IndexError):
            raise HTTPException(status_code=422, detail="AI could not parse bill — try a clearer PDF scan")
        except httpx.HTTPStatusError:
            continue

    raise HTTPException(status_code=503, detail="Gemini API unavailable")


def _extract_pdf_text(pdf_bytes: bytes) -> str:
    """Extract all text from PDF using pdfplumber."""
    try:
        import pdfplumber
    except ImportError:
        raise HTTPException(status_code=503, detail="pdfplumber not installed — rebuild container")

    text_parts = []
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        for page in pdf.pages:
            t = page.extract_text()
            if t:
                text_parts.append(t)
    return "\n".join(text_parts)


@router.post("/upload")
async def upload_bill(file: UploadFile = File(...)) -> Dict[str, Any]:
    """
    Upload a UHBVN PDF bill. Returns AI-parsed fields for user confirmation.
    Does NOT store anything yet — call /api/bills/confirm to save.
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files accepted")

    pdf_bytes = await file.read()
    if len(pdf_bytes) > 10 * 1024 * 1024:  # 10 MB cap
        raise HTTPException(status_code=400, detail="File too large (max 10 MB)")

    text = _extract_pdf_text(pdf_bytes)
    if len(text.strip()) < 50:
        raise HTTPException(status_code=422, detail="Could not extract text — is this a scanned image PDF?")

    parsed = await _call_gemini(EXTRACT_PROMPT, text)

    return {
        "status":    "parsed",
        "filename":  file.filename,
        "raw_chars": len(text),
        "parsed":    parsed,
    }


@router.post("/confirm")
async def confirm_bill(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Save confirmed bill data to InfluxDB after user reviews AI-parsed fields.
    Payload: the 'parsed' dict from /upload, optionally edited by the user.
    """
    p = payload.get("parsed", payload)

    # Parse billing period end as the timestamp for this data point
    period_to = p.get("billing_period_to")
    if period_to:
        try:
            ts = datetime.strptime(period_to, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            ts = datetime.now(timezone.utc)
    else:
        ts = datetime.now(timezone.utc)

    fields: Dict[str, Any] = {}
    for key in [
        "units_consumed_kwh", "units_exported_kwh", "net_units_billed_kwh",
        "previous_reading_kwh", "current_reading_kwh",
        "amount_before_tax_inr", "total_amount_inr",
    ]:
        v = p.get(key)
        if v is not None:
            try:
                fields[key] = float(v)
            except (TypeError, ValueError):
                pass

    for key in ["consumer_number", "meter_number", "billing_period_from",
                "billing_period_to", "tariff_category", "due_date"]:
        v = p.get(key)
        if v:
            fields[key] = str(v)

    if not fields:
        raise HTTPException(status_code=400, detail="No valid fields to store")

    # Derive self-consumed if we have both generation (from InfluxDB) and export
    exported = fields.get("units_exported_kwh")
    consumed = fields.get("units_consumed_kwh")

    write_api = get_client()
    from influxdb_client import Point
    from influxdb_client.client.write_api import SYNCHRONOUS

    point = Point("electricity_bill").time(ts)
    tags = {
        "source":   "uhbvn",
        "meter":    p.get("meter_number", "unknown"),
        "consumer": p.get("consumer_number", "unknown"),
    }
    for k, v in tags.items():
        point = point.tag(k, str(v))
    for k, v in fields.items():
        if isinstance(v, float):
            point = point.field(k, v)
        else:
            point = point.field(k, v)

    try:
        wa = write_api.write_api(write_options=SYNCHRONOUS)
        wa.write(bucket=BUCKET, record=point)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"InfluxDB write failed: {e}")

    return {
        "status":  "saved",
        "period":  period_to,
        "fields_saved": len(fields),
        "exported_kwh": exported,
        "consumed_kwh": consumed,
    }


@router.get("/history")
async def bill_history() -> Dict[str, Any]:
    """Return all stored bill records."""
    flux = f'''
from(bucket: "{BUCKET}")
  |> range(start: -5y)
  |> filter(fn: (r) => r["_measurement"] == "electricity_bill")
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
  |> sort(columns: ["_time"], desc: true)
'''
    recs = []
    try:
        from influx import query
        rows = query(flux)
        for r in rows:
            row_dict = {"time": str(r.get_time())}
            for field in [
                "billing_period_from", "billing_period_to", "units_consumed_kwh",
                "units_exported_kwh", "net_units_billed_kwh", "total_amount_inr",
                "consumer_number", "meter_number",
            ]:
                v = r.values.get(field)
                if v is not None:
                    row_dict[field] = v
            recs.append(row_dict)
    except Exception:
        pass

    return {"status": "success", "bills": recs}
