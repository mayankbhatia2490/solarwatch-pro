"use client";

import { useState, useRef } from "react";
import { Upload, FileText, CheckCircle, AlertCircle, Zap, IndianRupee, Calendar, RefreshCw, TrendingUp } from "lucide-react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "";

interface ParsedBill {
  consumer_number:       string | null;
  meter_number:          string | null;
  billing_period_from:   string | null;
  billing_period_to:     string | null;
  solar_generated_kwh:   number | null;
  units_imported_kwh:    number | null;
  units_exported_kwh:    number | null;
  net_units_billed_kwh:  number | null;
  total_amount_inr:      number | null;
  due_date:              string | null;
  tariff_category:       string | null;
  sanctioned_load_kw:    number | null;
  carry_forward_kwh:     number | null;
}

interface BillRecord {
  time:                 string;
  billing_period_from?: string;
  billing_period_to?:   string;
  units_consumed_kwh?:  number;
  units_exported_kwh?:  number;
  total_amount_inr?:    number;
  consumer_number?:     string;
}

function Field({ label, value, onChange, type = "text" }: {
  label: string; value: string; onChange: (v: string) => void; type?: string;
}) {
  return (
    <div>
      <label className="block text-xs mb-1" style={{ color: "var(--card-label)" }}>{label}</label>
      <input
        type={type}
        value={value}
        onChange={e => onChange(e.target.value)}
        className="w-full text-sm px-3 py-2 rounded-lg border outline-none focus:ring-1 focus:ring-emerald-500"
        style={{ background: "var(--bg-surface-2)", borderColor: "var(--bg-border)", color: "var(--card-value)" }}
      />
    </div>
  );
}

export default function BillsPage() {
  const [stage, setStage]       = useState<"idle"|"uploading"|"review"|"saving"|"done"|"error">("idle");
  const [parsed, setParsed]     = useState<ParsedBill | null>(null);
  const [filename, setFilename] = useState("");
  const [errMsg, setErrMsg]     = useState("");
  const [history, setHistory]   = useState<BillRecord[]>([]);
  const [histLoading, setHistLoading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  // Editable fields (all as strings for the form)
  const [form, setForm] = useState<Record<string, string>>({});

  function toForm(p: ParsedBill): Record<string, string> {
    const f: Record<string, string> = {};
    for (const [k, v] of Object.entries(p)) {
      f[k] = v != null ? String(v) : "";
    }
    return f;
  }

  async function handleFile(file: File) {
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setErrMsg("Only PDF files accepted"); setStage("error"); return;
    }
    setStage("uploading"); setErrMsg("");
    const fd = new FormData();
    fd.append("file", file);
    try {
      const res = await fetch(`${API}/api/bills/upload`, { method: "POST", body: fd });
      if (res.status === 413) throw new Error("File too large — nginx limit exceeded (check server config)");
      const text = await res.text();
      let json: any;
      try { json = JSON.parse(text); }
      catch { throw new Error(`Server error (${res.status}) — not JSON. Check API logs.`); }
      if (!res.ok) throw new Error(json.detail ?? "Upload failed");
      setParsed(json.parsed);
      setFilename(json.filename);
      setForm(toForm(json.parsed));
      setStage("review");
    } catch (e: any) {
      setErrMsg(e.message ?? "Upload failed"); setStage("error");
    }
  }

  async function handleConfirm() {
    setStage("saving");
    // Convert form strings back to typed values
    const out: Record<string, any> = {};
    const numFields = [
      "previous_reading_kwh","current_reading_kwh","units_consumed_kwh",
      "units_exported_kwh","net_units_billed_kwh","amount_before_tax_inr","total_amount_inr"
    ];
    for (const [k, v] of Object.entries(form)) {
      if (!v) { out[k] = null; continue; }
      out[k] = numFields.includes(k) ? parseFloat(v) : v;
    }
    try {
      const res = await fetch(`${API}/api/bills/confirm`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ parsed: out }),
      });
      const json = await res.json();
      if (!res.ok) throw new Error(json.detail ?? "Save failed");
      setStage("done");
      loadHistory();
    } catch (e: any) {
      setErrMsg(e.message ?? "Save failed"); setStage("error");
    }
  }

  async function loadHistory() {
    setHistLoading(true);
    try {
      const res = await fetch(`${API}/api/bills/history`);
      if (res.ok) { const j = await res.json(); setHistory(j.bills ?? []); }
    } finally { setHistLoading(false); }
  }

  // Load history on first render
  useState(() => { loadHistory(); });

  const fv = (k: string) => form[k] ?? "";
  const sf = (k: string) => (v: string) => setForm(f => ({ ...f, [k]: v }));

  // DHBVN sizing formula: kW Required = avg monthly units / 120
  const SYSTEM_KW = 3.57;
  const billsWithConsumption = history.filter(b => b.units_consumed_kwh != null && b.units_consumed_kwh > 0);
  const avgMonthlyKwh = billsWithConsumption.length > 0
    ? billsWithConsumption.reduce((s, b) => s + (b.units_consumed_kwh ?? 0), 0) / billsWithConsumption.length
    : null;
  const requiredKw   = avgMonthlyKwh != null ? avgMonthlyKwh / 120 : null;
  const suggestedMin = requiredKw != null ? requiredKw * 1.1 : null;
  const suggestedMax = requiredKw != null ? requiredKw * 1.2 : null;
  const sizingVerdict = requiredKw == null ? null
    : SYSTEM_KW < (suggestedMin ?? 0)  ? "undersized"
    : SYSTEM_KW > (suggestedMax ?? 0) * 1.1 ? "oversized"
    : "good";

  return (
    <div className="pt-16 lg:pt-0 space-y-6 max-w-4xl">
      <div>
        <h1 className="text-2xl font-bold" style={{ color: "var(--card-value)" }}>Electricity Bills</h1>
        <p className="text-sm mt-1" style={{ color: "var(--card-sub)" }}>
          Upload your UHBVN PDF bill — AI extracts the data, you confirm, we store it.
        </p>
      </div>

      {/* ── Upload zone ── */}
      {(stage === "idle" || stage === "error") && (
        <div
          className="glass-card rounded-2xl border-2 border-dashed p-10 flex flex-col items-center gap-4 cursor-pointer transition-colors hover:border-emerald-500/50"
          style={{ borderColor: stage === "error" ? "var(--color-red-500)" : "var(--bg-border)" }}
          onClick={() => inputRef.current?.click()}
          onDragOver={e => e.preventDefault()}
          onDrop={e => { e.preventDefault(); const f = e.dataTransfer.files[0]; if (f) handleFile(f); }}
        >
          <div className="w-14 h-14 rounded-2xl bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center">
            <Upload className="w-6 h-6 text-emerald-400" />
          </div>
          <div className="text-center">
            <p className="font-semibold" style={{ color: "var(--card-value)" }}>Drop your UHBVN PDF bill here</p>
            <p className="text-sm mt-1" style={{ color: "var(--card-sub)" }}>or click to browse · max 10 MB</p>
          </div>
          {stage === "error" && (
            <div className="flex items-center gap-2 text-red-400 text-sm">
              <AlertCircle className="w-4 h-4" /> {errMsg}
            </div>
          )}
          <input ref={inputRef} type="file" accept=".pdf" className="hidden"
            onChange={e => { const f = e.target.files?.[0]; if (f) handleFile(f); }} />
        </div>
      )}

      {/* ── Uploading spinner ── */}
      {stage === "uploading" && (
        <div className="glass-card rounded-2xl p-10 flex flex-col items-center gap-4">
          <RefreshCw className="w-8 h-8 text-emerald-400 animate-spin" />
          <p className="font-medium" style={{ color: "var(--card-value)" }}>Extracting &amp; parsing bill…</p>
          <p className="text-sm" style={{ color: "var(--card-sub)" }}>Gemini AI is reading your {filename}</p>
        </div>
      )}

      {/* ── Review / edit ── */}
      {(stage === "review" || stage === "saving") && parsed && (
        <div className="glass-card rounded-2xl p-6 space-y-5">
          <div className="flex items-center gap-3">
            <FileText className="w-5 h-5 text-emerald-400" />
            <div>
              <p className="font-semibold" style={{ color: "var(--card-value)" }}>Review extracted data</p>
              <p className="text-xs" style={{ color: "var(--card-sub)" }}>{filename} · Edit any incorrect values before saving</p>
            </div>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <Field label="Consumer Number"        value={fv("consumer_number")}       onChange={sf("consumer_number")} />
            <Field label="Solar Meter Number"     value={fv("meter_number")}          onChange={sf("meter_number")} />
            <Field label="Billing From"           value={fv("billing_period_from")}   onChange={sf("billing_period_from")} type="date" />
            <Field label="Billing To"             value={fv("billing_period_to")}     onChange={sf("billing_period_to")}   type="date" />
            <Field label="Solar Generated — KWHS (kWh)" value={fv("solar_generated_kwh")} onChange={sf("solar_generated_kwh")} type="number" />
            <Field label="Import from Grid — KWHI (kWh)" value={fv("units_imported_kwh")} onChange={sf("units_imported_kwh")}  type="number" />
            <Field label="Export to Grid — KWHE (kWh)"   value={fv("units_exported_kwh")} onChange={sf("units_exported_kwh")}  type="number" />
            <Field label="Net Units Billed (kWh)" value={fv("net_units_billed_kwh")}  onChange={sf("net_units_billed_kwh")} type="number" />
            <Field label="Net Payable Amount (₹ — negative = credit)" value={fv("total_amount_inr")} onChange={sf("total_amount_inr")} type="number" />
            <Field label="Carry Forward Units (kWh)" value={fv("carry_forward_kwh")} onChange={sf("carry_forward_kwh")} type="number" />
            <Field label="Due Date"               value={fv("due_date")}              onChange={sf("due_date")}             type="date" />
            <Field label="Tariff Category"        value={fv("tariff_category")}       onChange={sf("tariff_category")} />
          </div>

          <div className="flex gap-3 pt-2">
            <button
              onClick={handleConfirm}
              disabled={stage === "saving"}
              className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-emerald-500 hover:bg-emerald-600 text-white text-sm font-semibold transition-colors disabled:opacity-50"
            >
              {stage === "saving" ? <RefreshCw className="w-4 h-4 animate-spin" /> : <CheckCircle className="w-4 h-4" />}
              {stage === "saving" ? "Saving…" : "Confirm & Save"}
            </button>
            <button
              onClick={() => { setStage("idle"); setParsed(null); setForm({}); }}
              className="px-5 py-2.5 rounded-xl text-sm font-medium border transition-colors"
              style={{ borderColor: "var(--bg-border)", color: "var(--card-label)" }}
            >
              Cancel
            </button>
          </div>
        </div>
      )}

      {/* ── Done ── */}
      {stage === "done" && (
        <div className="glass-card rounded-2xl p-6 flex items-center gap-4 border border-emerald-500/25">
          <CheckCircle className="w-8 h-8 text-emerald-400 flex-shrink-0" />
          <div>
            <p className="font-semibold text-emerald-400">Bill saved successfully</p>
            <p className="text-sm mt-0.5" style={{ color: "var(--card-sub)" }}>Data stored in InfluxDB and visible in history below.</p>
          </div>
          <button
            onClick={() => { setStage("idle"); setParsed(null); setForm({}); }}
            className="ml-auto px-4 py-2 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-sm hover:bg-emerald-500/20 transition-colors"
          >
            Upload Another
          </button>
        </div>
      )}

      {/* ── System Sizing Analysis ── */}
      {avgMonthlyKwh != null && (
        <div className="glass-card rounded-2xl p-5 space-y-4">
          <div className="flex items-center gap-2">
            <TrendingUp className="w-4 h-4 text-emerald-400" />
            <h2 className="font-semibold" style={{ color: "var(--card-title)" }}>System Sizing Analysis</h2>
            <span className="text-xs ml-auto" style={{ color: "var(--card-sub)" }}>
              Based on {billsWithConsumption.length} bill{billsWithConsumption.length !== 1 ? "s" : ""} · DHBVN formula
            </span>
          </div>

          {/* Numbers row */}
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {[
              { label: "Avg Monthly Use",   value: `${avgMonthlyKwh.toFixed(0)} kWh`,          sub: "from your bills",          color: "text-blue-400" },
              { label: "Min Required",       value: `${requiredKw!.toFixed(2)} kW`,              sub: "monthly units ÷ 120",      color: "text-amber-400" },
              { label: "Suggested Range",    value: `${suggestedMin!.toFixed(1)}–${suggestedMax!.toFixed(1)} kW`, sub: "+10% to +20% buffer", color: "text-purple-400" },
              { label: "Your System",        value: `${SYSTEM_KW} kW`,                           sub: "installed capacity",       color: "text-emerald-400" },
            ].map(({ label, value, sub, color }) => (
              <div key={label} className="rounded-xl p-3" style={{ background: "var(--bg-surface-2)" }}>
                <div className={`text-lg font-bold ${color}`}>{value}</div>
                <div className="text-xs font-medium mt-0.5" style={{ color: "var(--card-label)" }}>{label}</div>
                <div className="text-xs mt-0.5" style={{ color: "var(--card-sub)" }}>{sub}</div>
              </div>
            ))}
          </div>

          {/* Visual bar */}
          <div className="space-y-1.5">
            <div className="text-xs" style={{ color: "var(--card-sub)" }}>
              Scale: 0 – {(Math.max(SYSTEM_KW, suggestedMax ?? 0) * 1.3).toFixed(1)} kW
            </div>
            {(() => {
              const maxScale = Math.max(SYSTEM_KW, suggestedMax ?? 0) * 1.3;
              const reqPct   = ((requiredKw  ?? 0) / maxScale * 100).toFixed(1);
              const minPct   = ((suggestedMin ?? 0) / maxScale * 100).toFixed(1);
              const maxPct   = ((suggestedMax ?? 0) / maxScale * 100).toFixed(1);
              const sysPct   = (SYSTEM_KW / maxScale * 100).toFixed(1);
              return (
                <div className="relative h-8 rounded-lg overflow-hidden" style={{ background: "var(--bg-surface-2)" }}>
                  {/* Suggested range band */}
                  <div className="absolute top-0 bottom-0 bg-emerald-500/20 border-l border-r border-emerald-500/40"
                    style={{ left: `${minPct}%`, width: `${(parseFloat(maxPct) - parseFloat(minPct)).toFixed(1)}%` }} />
                  {/* Required kW marker */}
                  <div className="absolute top-1 bottom-1 w-0.5 bg-amber-400" style={{ left: `${reqPct}%` }} />
                  {/* Your system marker */}
                  <div className="absolute top-0 bottom-0 w-1 rounded bg-emerald-400" style={{ left: `calc(${sysPct}% - 2px)` }} />
                  {/* Labels */}
                  <div className="absolute inset-0 flex items-center px-3 gap-4 text-xs pointer-events-none">
                    <span className="text-amber-400 font-medium">▲ Required: {requiredKw!.toFixed(2)} kW</span>
                    <span className="text-emerald-500/70 font-medium">▓ Suggested: {suggestedMin!.toFixed(1)}–{suggestedMax!.toFixed(1)} kW</span>
                    <span className="text-emerald-400 font-medium">▌ Yours: {SYSTEM_KW} kW</span>
                  </div>
                </div>
              );
            })()}
          </div>

          {/* Verdict */}
          <div className={`flex items-start gap-3 rounded-xl p-3 border ${
            sizingVerdict === "good"       ? "border-emerald-500/25 bg-emerald-500/5"  :
            sizingVerdict === "undersized" ? "border-amber-500/25 bg-amber-500/5"     :
                                             "border-blue-500/25 bg-blue-500/5"
          }`}>
            <span className="text-xl leading-none">
              {sizingVerdict === "good" ? "✅" : sizingVerdict === "undersized" ? "⚠️" : "ℹ️"}
            </span>
            <div>
              <p className="text-sm font-semibold" style={{ color: "var(--card-value)" }}>
                {sizingVerdict === "good"       && `Your ${SYSTEM_KW} kW system is well-matched to your consumption.`}
                {sizingVerdict === "undersized" && `Your ${SYSTEM_KW} kW system may be undersized for your consumption.`}
                {sizingVerdict === "oversized"  && `Your ${SYSTEM_KW} kW system has comfortable headroom above your needs.`}
              </p>
              <p className="text-xs mt-1" style={{ color: "var(--card-sub)" }}>
                {sizingVerdict === "good"       && `Falls within the recommended ${suggestedMin!.toFixed(1)}–${suggestedMax!.toFixed(1)} kW range. You have a healthy buffer for future load growth.`}
                {sizingVerdict === "undersized" && `Average consumption of ${avgMonthlyKwh.toFixed(0)} kWh/month needs at least ${requiredKw!.toFixed(1)} kW. Consider adding panels if roof space allows.`}
                {sizingVerdict === "oversized"  && `Your system can comfortably cover your ${avgMonthlyKwh.toFixed(0)} kWh/month average and handle future load additions like an EV or AC.`}
              </p>
            </div>
          </div>
        </div>
      )}

      {/* ── History ── */}
      <div className="glass-card rounded-2xl p-5">
        <div className="flex items-center justify-between mb-4">
          <h2 className="font-semibold" style={{ color: "var(--card-title)" }}>Bill History</h2>
          <button onClick={loadHistory} className="p-1.5 rounded-lg hover:bg-slate-700/50 transition-colors">
            <RefreshCw className={`w-3.5 h-3.5 text-slate-400 ${histLoading ? "animate-spin" : ""}`} />
          </button>
        </div>

        {history.length === 0 ? (
          <p className="text-sm text-center py-8" style={{ color: "var(--card-sub)" }}>
            No bills stored yet — upload your first UHBVN bill above.
          </p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr>
                  {["Period", "Solar Gen (kWh)", "Import (kWh)", "Export (kWh)", "Amount (₹)"].map(h => (
                    <th key={h} className="text-left pb-3 pr-4 text-xs font-medium" style={{ color: "var(--card-label)" }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {history.map((b, i) => (
                  <tr key={i} className="border-t" style={{ borderColor: "var(--bg-border)" }}>
                    <td className="py-3 pr-4" style={{ color: "var(--card-value)" }}>
                      <div className="flex items-center gap-1.5">
                        <Calendar className="w-3 h-3 text-slate-500" />
                        {b.billing_period_from && b.billing_period_to
                          ? `${b.billing_period_from} → ${b.billing_period_to}`
                          : new Date(b.time).toLocaleDateString("en-IN")}
                      </div>
                    </td>
                    <td className="py-3 pr-4">
                      <div className="flex items-center gap-1 text-amber-400">
                        <Zap className="w-3 h-3" />
                        {(b as any).solar_generated_kwh != null ? (b as any).solar_generated_kwh.toFixed(0) : "—"}
                      </div>
                    </td>
                    <td className="py-3 pr-4">
                      <div className="flex items-center gap-1 text-blue-400">
                        <Zap className="w-3 h-3" />
                        {(b as any).units_imported_kwh != null ? (b as any).units_imported_kwh.toFixed(0) : "—"}
                      </div>
                    </td>
                    <td className="py-3 pr-4">
                      <div className="flex items-center gap-1 text-emerald-400">
                        <Zap className="w-3 h-3" />
                        {b.units_exported_kwh != null ? b.units_exported_kwh.toFixed(0) : "—"}
                      </div>
                    </td>
                    <td className="py-3">
                      <div className={`flex items-center gap-1 ${(b.total_amount_inr ?? 0) < 0 ? "text-emerald-400" : "text-amber-400"}`}>
                        <IndianRupee className="w-3 h-3" />
                        {b.total_amount_inr != null ? b.total_amount_inr.toFixed(0) : "—"}
                        {(b.total_amount_inr ?? 0) < 0 && <span className="text-xs">(credit)</span>}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
