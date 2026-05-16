"""
UHBVN Electricity Bill Upload & Parse — POST /api/bills/upload
Sends the PDF directly to Gemini as inline_data (native multimodal PDF understanding).
No pdfplumber text extraction — Gemini reads the complex UHBVN table layout natively.
"""
from fastapi import APIRouter, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse
from typing import Dict, Any
from datetime import datetime, timezone
import base64
import io
import json
import httpx

from config import settings
from influx import get_client

router = APIRouter(prefix="/api/bills", tags=["Bills"])

BUCKET = settings.influxdb_bucket

EXTRACT_PROMPT = """
You are reading a UHBVN (Uttar Haryana Bijli Vitran Nigam) electricity bill.
This is a net metering bill with THREE separate meters on it:
  - KWHE = Export units (solar sent to grid)
  - KWHI = Import units (electricity taken from grid)
  - KWHS = Solar generated units (total solar production from your panels)

Extract these fields and return ONLY a valid JSON object with these exact keys.
Use null if a field is genuinely not present. Do NOT guess — use null for missing values.

{
  "consumer_number": "account number shown near top of bill",
  "meter_number": "the solar meter number (the one labelled KWHS)",
  "billing_period_from": "YYYY-MM-DD format of billing period start date",
  "billing_period_to": "YYYY-MM-DD format of billing period end date",
  "solar_generated_kwh": number — Solar Generated Units (KWHS consumed column),
  "units_imported_kwh": number — Import units from grid (KWHI consumed column),
  "units_exported_kwh": number — Export units to grid (KWHE consumed column),
  "net_units_billed_kwh": number — Net Billed Units (after netting solar against import),
  "total_amount_inr": number — Net Payable Amount (can be negative if in credit),
  "due_date": "YYYY-MM-DD format",
  "tariff_category": "DS or NDS or other category shown on bill",
  "sanctioned_load_kw": number — Sanctioned Load in kW,
  "carry_forward_kwh": number — Carried Forward KWH to next bill (credit units)
}
"""


async def _call_gemini_with_pdf(pdf_bytes: bytes) -> dict:
    """Send PDF directly to Gemini as inline base64 — far more accurate than text extraction."""
    api_key = settings.gemini_api_key
    if not api_key:
        raise HTTPException(status_code=503, detail="GEMINI_API_KEY not configured")

    b64 = base64.b64encode(pdf_bytes).decode()

    # Try configured model first, then fallbacks in recency order.
    # gemini-2.5-flash supports native PDF inline_data; older models may not.
    models = [
        settings.gemini_model,
        "gemini-2.5-flash",
        "gemini-2.0-flash",
        "gemini-2.0-flash-lite",
        "gemini-1.5-pro",
    ]
    # Deduplicate while preserving order
    seen: set = set()
    models = [m for m in models if m and not (m in seen or seen.add(m))]

    last_error = "Gemini API unavailable"
    for model in models:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{model}:generateContent?key={api_key}"
        )
        payload = {
            "contents": [{
                "parts": [
                    {
                        "inline_data": {
                            "mime_type": "application/pdf",
                            "data": b64,
                        }
                    },
                    {"text": EXTRACT_PROMPT},
                ]
            }],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 4096,  # 1024 truncated the JSON response
            },
        }
        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(url, json=payload)
                if resp.status_code == 404:
                    last_error = f"Model {model} not found"
                    continue
                if resp.status_code == 400:
                    last_error = f"Model {model} rejected request: {resp.text[:200]}"
                    continue
                resp.raise_for_status()
                data = resp.json()
                raw = data["candidates"][0]["content"]["parts"][0]["text"].strip()
                # Strip markdown fences if present
                if raw.startswith("```"):
                    raw = raw.split("```")[1]
                    if raw.startswith("json"):
                        raw = raw[4:]
                raw = raw.strip()
                # Guard: if still truncated, try to close the JSON object
                if not raw.endswith("}"):
                    raw = raw.rsplit(",", 1)[0] + "\n}"
                return json.loads(raw)
        except json.JSONDecodeError as e:
            last_error = f"JSON parse error ({e})"
            continue   # try next model rather than giving up immediately
        except (KeyError, IndexError):
            last_error = "Gemini response was empty or malformed"
            continue
        except httpx.HTTPStatusError as e:
            last_error = f"HTTP {e.response.status_code}: {e.response.text[:200]}"
            continue
        except Exception as e:
            last_error = str(e)
            continue

    raise HTTPException(status_code=503, detail=f"All Gemini models failed. Last error: {last_error}")


@router.post("/upload")
async def upload_bill(file: UploadFile = File(...)) -> Dict[str, Any]:
    """
    Upload a UHBVN PDF bill. PDF is sent directly to Gemini for native parsing.
    Returns AI-parsed fields for user review — call /confirm to save.
    """
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files accepted")

    pdf_bytes = await file.read()
    if len(pdf_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File too large (max 10 MB)")
    if len(pdf_bytes) < 1000:
        raise HTTPException(status_code=400, detail="File appears to be empty or corrupt")

    parsed = await _call_gemini_with_pdf(pdf_bytes)

    # Back-fill units_consumed_kwh for backwards compat (= import from grid)
    if "units_imported_kwh" in parsed and parsed.get("units_imported_kwh") is not None:
        parsed.setdefault("units_consumed_kwh", parsed["units_imported_kwh"])

    return {
        "status":   "parsed",
        "filename": file.filename,
        "parsed":   parsed,
    }


@router.post("/confirm")
async def confirm_bill(payload: Dict[str, Any]) -> Dict[str, Any]:
    """
    Save confirmed bill data to InfluxDB after user reviews AI-parsed fields.
    """
    p = payload.get("parsed", payload)

    period_to = p.get("billing_period_to")
    try:
        ts = datetime.strptime(period_to, "%Y-%m-%d").replace(tzinfo=timezone.utc) if period_to else datetime.now(timezone.utc)
    except ValueError:
        ts = datetime.now(timezone.utc)

    num_fields = [
        "solar_generated_kwh", "units_imported_kwh", "units_exported_kwh",
        "units_consumed_kwh", "net_units_billed_kwh",
        "total_amount_inr", "amount_before_tax_inr",
        "previous_reading_kwh", "current_reading_kwh",
        "sanctioned_load_kw", "carry_forward_kwh",
    ]
    str_fields = [
        "consumer_number", "meter_number", "billing_period_from",
        "billing_period_to", "tariff_category", "due_date",
    ]

    fields: Dict[str, Any] = {}
    for key in num_fields:
        v = p.get(key)
        if v is not None:
            try:
                fields[key] = float(v)
            except (TypeError, ValueError):
                pass
    for key in str_fields:
        v = p.get(key)
        if v:
            fields[key] = str(v)

    if not fields:
        raise HTTPException(status_code=400, detail="No valid fields to store")

    write_api = get_client()
    from influxdb_client import Point
    from influxdb_client.client.write_api import SYNCHRONOUS

    point = Point("electricity_bill").time(ts)
    for k, v in {
        "source":   "uhbvn",
        "meter":    p.get("meter_number", "unknown"),
        "consumer": p.get("consumer_number", "unknown"),
    }.items():
        point = point.tag(k, str(v))
    for k, v in fields.items():
        point = point.field(k, v)

    try:
        wa = write_api.write_api(write_options=SYNCHRONOUS)
        wa.write(bucket=BUCKET, record=point)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"InfluxDB write failed: {e}")

    return {
        "status":            "saved",
        "period":            period_to,
        "fields_saved":      len(fields),
        "solar_kwh":         fields.get("solar_generated_kwh"),
        "imported_kwh":      fields.get("units_imported_kwh"),
        "exported_kwh":      fields.get("units_exported_kwh"),
        "net_billed_kwh":    fields.get("net_units_billed_kwh"),
        "total_amount_inr":  fields.get("total_amount_inr"),
    }


@router.get("/history")
async def bill_history() -> Dict[str, Any]:
    """Return all stored bill records, newest first."""
    from influx import query
    flux = f'''
from(bucket: "{BUCKET}")
  |> range(start: -5y)
  |> filter(fn: (r) => r["_measurement"] == "electricity_bill")
  |> sort(columns: ["_time"], desc: true)
'''
    recs: dict[str, dict] = {}
    try:
        rows = query(flux)
        for r in rows:
            ts = str(r.get_time())
            if ts not in recs:
                recs[ts] = {"time": ts}
            field = r.values.get("_field")
            val   = r.get_value()
            if field and val is not None:
                recs[ts][field] = val
    except Exception:
        pass

    return {"status": "success", "bills": list(recs.values())}
