"""
UHBVN Electricity Bill Upload & Parse — POST /api/bills/upload
Sends the PDF directly to Gemini as inline_data (native multimodal PDF understanding).
No pdfplumber text extraction — Gemini reads the complex UHBVN table layout natively.

On confirm: queries Shinemonitor raw data for the billing period to measure the
actual inverter↔utility-meter discrepancy and auto-updates the correction factor.
"""
from fastapi import APIRouter, UploadFile, File, HTTPException
from typing import Dict, Any, Optional
from datetime import datetime, timezone, timedelta
import base64
import json
import httpx

from config import settings, _OVERRIDE_FILE
from influx import get_client, query as influx_query

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
                "maxOutputTokens": 4096,
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
                # Guard: if still truncated, close the JSON object at the last complete field
                if not raw.endswith("}"):
                    raw = raw.rsplit(",", 1)[0] + "\n}"
                return json.loads(raw)
        except json.JSONDecodeError as e:
            last_error = f"JSON parse error ({e})"
            continue
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


def _query_shinemonitor_for_period(from_date: str, to_date: str) -> float:
    """
    Sum raw Shinemonitor daily_energy_kwh for a billing period.
    InfluxDB stores the raw inverter values (correction is applied only at read time),
    so we sum the max per IST day directly without un-applying anything.
    Returns 0.0 if no data found for the period.
    """
    _IST = timezone(timedelta(hours=5, minutes=30))
    flux = f'''
from(bucket: "{BUCKET}")
  |> range(start: {from_date}T00:00:00Z, stop: {to_date}T23:59:59Z)
  |> filter(fn: (r) => r["_field"] == "daily_energy_kwh")
  |> filter(fn: (r) => r["_value"] > 0)
  |> sort(columns: ["_time"])
'''
    recs = influx_query(flux)
    day_max: dict[str, float] = {}
    for rec in recs:
        day_key = rec.get_time().astimezone(_IST).strftime("%Y-%m-%d")
        val = float(rec.get_value() or 0)
        if val > day_max.get(day_key, 0.0):
            day_max[day_key] = val
    return round(sum(day_max.values()), 2)


def _update_correction_factor(new_factor: float) -> None:
    """Persist the latest meter correction to settings_override.json and apply in-memory."""
    try:
        data: dict = {}
        if _OVERRIDE_FILE.exists():
            data = json.loads(_OVERRIDE_FILE.read_text())
        data["shinemonitor_correction"] = round(new_factor, 4)
        _OVERRIDE_FILE.parent.mkdir(parents=True, exist_ok=True)
        _OVERRIDE_FILE.write_text(json.dumps(data, indent=2))
        object.__setattr__(settings, "shinemonitor_correction", round(new_factor, 4))
        print(f"shinemonitor_correction updated to {new_factor:.4f} from bill data")
    except Exception as e:
        print(f"Could not persist correction factor: {e}")


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
    Also compares Shinemonitor app data vs UHBVN meter for the billing period
    and auto-updates the correction factor if discrepancy is measured.
    """
    p = payload.get("parsed", payload)

    period_from = p.get("billing_period_from")
    period_to   = p.get("billing_period_to")
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

    # ── Meter comparison: Shinemonitor app vs UHBVN physical meter ──────────────
    meter_comparison: Dict[str, Any] = {}
    bill_solar_kwh = fields.get("solar_generated_kwh")
    if period_from and period_to and bill_solar_kwh and bill_solar_kwh > 0:
        try:
            app_raw_kwh = _query_shinemonitor_for_period(period_from, period_to)
            if app_raw_kwh > 0:
                correction = bill_solar_kwh / app_raw_kwh
                fields["shinemonitor_raw_kwh"]    = app_raw_kwh
                fields["meter_correction_factor"] = round(correction, 4)
                meter_comparison = {
                    "app_reported_kwh":  app_raw_kwh,
                    "uhbvn_meter_kwh":   bill_solar_kwh,
                    "correction_factor": round(correction, 4),
                    "over_read_pct":     round((app_raw_kwh / bill_solar_kwh - 1) * 100, 1),
                }
                # Auto-update the system correction factor
                _update_correction_factor(correction)
        except Exception as e:
            print(f"Meter comparison skipped: {e}")

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
        "meter_comparison":  meter_comparison or None,
    }


def _load_all_bills() -> list[dict]:
    """Fetch all electricity_bill records from InfluxDB, newest first."""
    flux = f'''
from(bucket: "{BUCKET}")
  |> range(start: -5y)
  |> filter(fn: (r) => r["_measurement"] == "electricity_bill")
  |> sort(columns: ["_time"], desc: false)
'''
    recs: dict[str, dict] = {}
    try:
        rows = influx_query(flux)
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
    return sorted(recs.values(), key=lambda b: b["time"])


@router.get("/history")
async def bill_history() -> Dict[str, Any]:
    """Return all stored bill records, newest first."""
    bills = list(reversed(_load_all_bills()))
    return {"status": "success", "bills": bills}


@router.get("/insights")
async def bill_insights() -> Dict[str, Any]:
    """
    Cross-bill intelligence: meter accuracy trend, consumption patterns, anomalies.
    Grows more accurate as more bills are added.
    """
    bill_list = _load_all_bills()

    if not bill_list:
        return {"bills": [], "summary": None, "message": "No bills stored yet"}

    analyzed = []
    for b in bill_list:
        solar_kwh  = b.get("solar_generated_kwh")
        import_kwh = b.get("units_imported_kwh")
        export_kwh = b.get("units_exported_kwh")
        app_kwh    = b.get("shinemonitor_raw_kwh")
        correction = b.get("meter_correction_factor")

        # Total household consumption = solar used directly + grid import
        total_consumption: Optional[float] = None
        if solar_kwh is not None and import_kwh is not None and export_kwh is not None:
            total_consumption = round(solar_kwh + import_kwh - export_kwh, 1)

        # Self-consumption ratio (how much solar stayed in the house vs exported)
        self_consumption_pct: Optional[float] = None
        if solar_kwh and solar_kwh > 0 and export_kwh is not None:
            self_consumption_pct = round((solar_kwh - export_kwh) / solar_kwh * 100, 1)

        # Solar offset ratio (solar vs total consumption)
        solar_offset_pct: Optional[float] = None
        if solar_kwh and total_consumption and total_consumption > 0:
            solar_offset_pct = round(solar_kwh / total_consumption * 100, 1)

        # Meter discrepancy
        over_read_pct: Optional[float] = None
        if app_kwh and solar_kwh and solar_kwh > 0:
            over_read_pct = round((app_kwh / solar_kwh - 1) * 100, 1)

        # ── Anomaly & billing error detection ───────────────────────────────────
        anomalies: list[dict] = []

        # 1. Meter discrepancy unusually high (inverter issue / meter fault)
        if over_read_pct is not None:
            if over_read_pct > 18:
                anomalies.append({
                    "level": "warning",
                    "code": "HIGH_METER_DISCREPANCY",
                    "title": f"App over-reads UHBVN meter by {over_read_pct:.1f}%",
                    "detail": (
                        f"Shinemonitor reports {app_kwh:.1f} kWh but UHBVN KWHS meter shows {solar_kwh:.1f} kWh "
                        f"— {over_read_pct:.1f}% gap is unusually high. "
                        "Possible causes: inverter internal counter drift, meter calibration issue, "
                        "or data collected across different period boundaries."
                    ),
                    "action": "Compare meter reading dates carefully. If persistent across 2+ bills, request UHBVN meter re-test.",
                })
            elif over_read_pct < 1.0:
                anomalies.append({
                    "level": "info",
                    "code": "METERS_CLOSELY_ALIGNED",
                    "title": "Shinemonitor and UHBVN meter nearly identical",
                    "detail": f"Only {over_read_pct:.1f}% difference — excellent meter correlation this period.",
                    "action": None,
                })

        # 2. Net metering arithmetic check — net_billed should ≈ import - export
        net_billed = b.get("net_units_billed_kwh")
        if import_kwh and export_kwh is not None and net_billed is not None:
            expected_net = import_kwh - export_kwh
            net_error = net_billed - expected_net
            if abs(net_error) > 5:  # tolerance: 5 kWh rounding
                anomalies.append({
                    "level": "error",
                    "code": "NET_BILLED_MISMATCH",
                    "title": f"Net billed units don't match — {abs(net_error):.0f} kWh discrepancy",
                    "detail": (
                        f"Expected net billed = Import ({import_kwh:.0f}) − Export ({export_kwh:.0f}) = {expected_net:.0f} kWh, "
                        f"but bill shows {net_billed:.0f} kWh. "
                        f"This {net_error:+.0f} kWh gap could mean UHBVN did not fully credit your exported solar."
                    ),
                    "action": "Challenge this bill at UHBVN consumer grievance portal with your KWHE meter reading.",
                })

        # 3. Export units not credited (export > 0 but charged as if no solar)
        if export_kwh and export_kwh > 10 and net_billed is not None and import_kwh is not None:
            if net_billed >= import_kwh * 0.95:  # net billed is nearly equal to import — no credit given
                anomalies.append({
                    "level": "error",
                    "code": "EXPORT_NOT_CREDITED",
                    "title": f"Export ({export_kwh:.0f} kWh) may not have been deducted from your bill",
                    "detail": (
                        f"You exported {export_kwh:.0f} kWh to the grid but net billed ({net_billed:.0f} kWh) "
                        f"is almost the same as your import ({import_kwh:.0f} kWh). "
                        "Under UHBVN net metering, exports must be subtracted."
                    ),
                    "action": "Request a bill correction citing UHBVN Net Metering Regulation 2.3 — exports must be offset against imports.",
                })

        # 4. Credit carry-forward missing when export > import
        carry_fwd = b.get("carry_forward_kwh")
        if export_kwh and import_kwh is not None and export_kwh > import_kwh:
            net_credit = export_kwh - import_kwh
            if (carry_fwd is None or carry_fwd < net_credit * 0.8):
                anomalies.append({
                    "level": "warning",
                    "code": "CARRY_FORWARD_LOW",
                    "title": f"Expected ≥{net_credit:.0f} kWh carry-forward, got {carry_fwd or 0:.0f} kWh",
                    "detail": (
                        f"Your export ({export_kwh:.0f} kWh) exceeded import ({import_kwh:.0f} kWh) by {net_credit:.0f} kWh. "
                        "This surplus should carry forward to the next billing period under UHBVN net metering."
                    ),
                    "action": "Verify carry-forward on next bill. If missing, raise a grievance with UHBVN.",
                })

        # 5. Positive amount despite net credit (should be zero or credit)
        amount_inr = b.get("total_amount_inr")
        if amount_inr and amount_inr > 50 and export_kwh and import_kwh is not None and export_kwh > import_kwh:
            anomalies.append({
                "level": "warning",
                "code": "CHARGED_DESPITE_NET_CREDIT",
                "title": f"Charged ₹{amount_inr:.0f} despite exporting more than importing",
                "detail": (
                    f"You exported more ({export_kwh:.0f} kWh) than you imported ({import_kwh:.0f} kWh) "
                    f"yet the bill charges ₹{amount_inr:.0f}. Fixed charges (meter rent, duty) may apply, "
                    "but verify no energy units are being billed incorrectly."
                ),
                "action": "Request itemised bill breakdown from UHBVN to confirm only fixed charges are being levied.",
            })

        # 6. Unusually low self-consumption (system may be undersized for daytime loads)
        if self_consumption_pct is not None and self_consumption_pct < 25:
            anomalies.append({
                "level": "info",
                "code": "LOW_SELF_CONSUMPTION",
                "title": f"Only {self_consumption_pct:.0f}% of solar used in-house — most exported",
                "detail": (
                    "This is not an error, but it means your peak generation time doesn't match "
                    "your peak consumption. Shifting heavy loads (AC, washing machine, water heater) "
                    "to daytime hours will improve self-consumption and reduce grid dependency."
                ),
                "action": "Shift daytime loads to 10 AM–3 PM solar peak hours.",
            })

        analyzed.append({
            "period_from":          b.get("billing_period_from"),
            "period_to":            b.get("billing_period_to"),
            "solar_kwh_bill":       solar_kwh,
            "solar_kwh_app":        round(app_kwh, 1) if app_kwh else None,
            "meter_correction":     round(correction, 4) if correction else None,
            "over_read_pct":        over_read_pct,
            "import_kwh":           import_kwh,
            "export_kwh":           export_kwh,
            "total_consumption_kwh": total_consumption,
            "self_consumption_pct": self_consumption_pct,
            "solar_offset_pct":     solar_offset_pct,
            "amount_inr":           b.get("total_amount_inr"),
            "carry_forward_kwh":    b.get("carry_forward_kwh"),
            "anomalies":            anomalies,
        })

    # Summary across all bills
    corrections    = [b["meter_correction"]      for b in analyzed if b["meter_correction"]      is not None]
    consumptions   = [b["total_consumption_kwh"] for b in analyzed if b["total_consumption_kwh"] is not None]
    solar_offsets  = [b["solar_offset_pct"]      for b in analyzed if b["solar_offset_pct"]      is not None]
    self_cons_list = [b["self_consumption_pct"]  for b in analyzed if b["self_consumption_pct"]  is not None]

    summary = {
        "bill_count":                    len(analyzed),
        "bills_with_meter_comparison":   len(corrections),
        "avg_correction_factor":         round(sum(corrections) / len(corrections), 4) if corrections else None,
        "latest_correction_factor":      corrections[-1] if corrections else None,
        "avg_monthly_consumption_kwh":   round(sum(consumptions) / len(consumptions), 1) if consumptions else None,
        "avg_solar_offset_pct":          round(sum(solar_offsets) / len(solar_offsets), 1) if solar_offsets else None,
        "avg_self_consumption_pct":      round(sum(self_cons_list) / len(self_cons_list), 1) if self_cons_list else None,
        "current_correction_factor":     settings.shinemonitor_correction,
    }

    return {"bills": analyzed, "summary": summary}
