"use client";

import { useState, useRef, useEffect } from "react";
import {
  Upload, FileText, CheckCircle, AlertCircle, Zap, IndianRupee,
  Calendar, RefreshCw, TrendingUp, BarChart2, AlertTriangle, Info,
} from "lucide-react";

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

interface BillAnomaly {
  level:  "error" | "warning" | "info";
  code:   string;
  title:  string;
  detail: string;
  action: string | null;
}

interface BillInsight {
  period_from:           string | null;
  period_to:             string | null;
  solar_kwh_bill:        number | null;
  solar_kwh_app:         number | null;
  meter_correction:      number | null;
  over_read_pct:         number | null;
  import_kwh:            number | null;
  export_kwh:            number | null;
  total_consumption_kwh: number | null;
  self_consumption_pct:  number | null;
  solar_offset_pct:      number | null;
  amount_inr:            number | null;
  carry_forward_kwh:     number | null;
  anomalies:             BillAnomaly[];
}

interface InsightsSummary {
  bill_count:                  number;
  bills_with_meter_comparison: number;
  avg_correction_factor:       number | null;
  latest_correction_factor:    number | null;
  avg_monthly_consumption_kwh: number | null;
  avg_solar_offset_pct:        number | null;
  avg_self_consumption_pct:    number | null;
  current_correction_factor:   number;
}

function Field({ label, value, onChange, type = "text" }: {
  label: string; value: string; onChange: (v: string) => void; type?: string;
}) {
  return (
    <div>
      <label className="block text-xs mb-1" style={{ color: "var(--card-label)" }}>{label}</label>
      <input
        type={type} value={value} onChange={e => onChange(e.target.value)}
        className="w-full text-sm px-3 py-2 rounded-lg border outline-none focus:ring-1 focus:ring-emerald-500"
        style={{ background: "var(--bg-surface-2)", borderColor: "var(--bg-border)", color: "var(--card-value)" }}
      />
    </div>
  );
}

function MiniStat({ label, value, sub, color = "text-emerald-400" }: {
  label: string; value: string; sub?: string; color?: string;
}) {
  return (
    <div className="rounded-xl p-3" style={{ background: "var(--bg-surface-2)" }}>
      <div className={`text-lg font-bold ${color}`}>{value}</div>
      <div className="text-xs font-medium mt-0.5" style={{ color: "var(--card-label)" }}>{label}</div>
      {sub && <div className="text-xs mt-0.5" style={{ color: "var(--card-sub)" }}>{sub}</div>}
    </div>
  );
}

function periodLabel(from: string | null, to: string | null): string {
  if (!from && !to) return "Unknown period";
  const fmt = (d: string) => {
    const [y, m] = d.split("-");
    return `${["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"][parseInt(m)-1]} ${y}`;
  };
  if (from && to) return `${fmt(from)} → ${fmt(to)}`;
  return fmt(from ?? to ?? "");
}

export default function BillsPage() {
  const [stage, setStage]     = useState<"idle"|"uploading"|"review"|"saving"|"done"|"error">("idle");
  const [parsed, setParsed]   = useState<ParsedBill | null>(null);
  const [filename, setFilename] = useState("");
  const [errMsg, setErrMsg]   = useState("");
  const [form, setForm]       = useState<Record<string, string>>({});
  const [insights, setInsights] = useState<{ bills: BillInsight[]; summary: InsightsSummary | null } | null>(null);
  const [insightsLoading, setInsightsLoading] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  function toForm(p: ParsedBill): Record<string, string> {
    const f: Record<string, string> = {};
    for (const [k, v] of Object.entries(p)) f[k] = v != null ? String(v) : "";
    return f;
  }

  async function loadInsights() {
    setInsightsLoading(true);
    try {
      const res = await fetch(`${API}/api/bills/insights`);
      if (res.ok) setInsights(await res.json());
    } finally { setInsightsLoading(false); }
  }

  useEffect(() => { loadInsights(); }, []);

  async function handleFile(file: File) {
    if (!file.name.toLowerCase().endsWith(".pdf")) {
      setErrMsg("Only PDF files accepted"); setStage("error"); return;
    }
    setStage("uploading"); setErrMsg("");
    const fd = new FormData();
    fd.append("file", file);
    try {
      const res = await fetch(`${API}/api/bills/upload`, { method: "POST", body: fd });
      if (res.status === 413) throw new Error("File too large — check nginx client_max_body_size");
      const text = await res.text();
      let json: any;
      try { json = JSON.parse(text); }
      catch { throw new Error(`Server error (${res.status}) — check API logs`); }
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
    const numFields = [
      "previous_reading_kwh","current_reading_kwh","units_consumed_kwh",
      "solar_generated_kwh","units_exported_kwh","net_units_billed_kwh",
      "units_imported_kwh","amount_before_tax_inr","total_amount_inr",
      "sanctioned_load_kw","carry_forward_kwh",
    ];
    const out: Record<string, any> = {};
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
      loadInsights();
    } catch (e: any) {
      setErrMsg(e.message ?? "Save failed"); setStage("error");
    }
  }

  const fv = (k: string) => form[k] ?? "";
  const sf = (k: string) => (v: string) => setForm(f => ({ ...f, [k]: v }));
  const s = insights?.summary;
  const bills = insights?.bills ?? [];

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
            <Field label="Consumer Number"                       value={fv("consumer_number")}       onChange={sf("consumer_number")} />
            <Field label="Solar Meter Number"                    value={fv("meter_number")}          onChange={sf("meter_number")} />
            <Field label="Billing From"                          value={fv("billing_period_from")}   onChange={sf("billing_period_from")} type="date" />
            <Field label="Billing To"                            value={fv("billing_period_to")}     onChange={sf("billing_period_to")} type="date" />
            <Field label="Solar Generated — KWHS (kWh)"          value={fv("solar_generated_kwh")}   onChange={sf("solar_generated_kwh")} type="number" />
            <Field label="Import from Grid — KWHI (kWh)"         value={fv("units_imported_kwh")}    onChange={sf("units_imported_kwh")} type="number" />
            <Field label="Export to Grid — KWHE (kWh)"           value={fv("units_exported_kwh")}    onChange={sf("units_exported_kwh")} type="number" />
            <Field label="Net Units Billed (kWh)"                value={fv("net_units_billed_kwh")}  onChange={sf("net_units_billed_kwh")} type="number" />
            <Field label="Net Payable (₹ — negative = credit)"   value={fv("total_amount_inr")}      onChange={sf("total_amount_inr")} type="number" />
            <Field label="Carry Forward Units (kWh)"             value={fv("carry_forward_kwh")}     onChange={sf("carry_forward_kwh")} type="number" />
            <Field label="Due Date"                              value={fv("due_date")}              onChange={sf("due_date")} type="date" />
            <Field label="Tariff Category"                       value={fv("tariff_category")}       onChange={sf("tariff_category")} />
          </div>

          <div className="flex gap-3 pt-2">
            <button onClick={handleConfirm} disabled={stage === "saving"}
              className="flex items-center gap-2 px-5 py-2.5 rounded-xl bg-emerald-500 hover:bg-emerald-600 text-white text-sm font-semibold transition-colors disabled:opacity-50">
              {stage === "saving" ? <RefreshCw className="w-4 h-4 animate-spin" /> : <CheckCircle className="w-4 h-4" />}
              {stage === "saving" ? "Saving…" : "Confirm & Save"}
            </button>
            <button onClick={() => { setStage("idle"); setParsed(null); setForm({}); }}
              className="px-5 py-2.5 rounded-xl text-sm font-medium border transition-colors"
              style={{ borderColor: "var(--bg-border)", color: "var(--card-label)" }}>
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
            <p className="text-sm mt-0.5" style={{ color: "var(--card-sub)" }}>
              Shinemonitor vs UHBVN meter comparison computed and correction factor updated.
            </p>
          </div>
          <button onClick={() => { setStage("idle"); setParsed(null); setForm({}); }}
            className="ml-auto px-4 py-2 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 text-sm hover:bg-emerald-500/20 transition-colors">
            Upload Another
          </button>
        </div>
      )}

      {/* ── Bill Intelligence ── */}
      {bills.length > 0 && s && (
        <div className="space-y-4">
          <div className="flex items-center gap-2">
            <BarChart2 className="w-4 h-4 text-emerald-400" />
            <h2 className="font-semibold" style={{ color: "var(--card-title)" }}>Bill Intelligence</h2>
            <span className="text-xs ml-auto" style={{ color: "var(--card-sub)" }}>
              {s.bill_count} bill{s.bill_count !== 1 ? "s" : ""} analysed · grows smarter with each upload
            </span>
          </div>

          {/* ── Meter accuracy card ── */}
          {s.bills_with_meter_comparison > 0 && (
            <div className="glass-card rounded-2xl p-5 space-y-4">
              <div className="flex items-center justify-between">
                <h3 className="text-sm font-semibold" style={{ color: "var(--card-value)" }}>
                  Shinemonitor vs UHBVN Meter Accuracy
                </h3>
                <span className="text-xs px-2 py-0.5 rounded-full bg-blue-500/10 border border-blue-500/20 text-blue-400">
                  {s.bills_with_meter_comparison} period{s.bills_with_meter_comparison !== 1 ? "s" : ""} measured
                </span>
              </div>

              <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
                <MiniStat
                  label="Current Correction"
                  value={`${(s.current_correction_factor * 100).toFixed(1)}%`}
                  sub="applied to all readings"
                  color="text-emerald-400"
                />
                <MiniStat
                  label="App Over-reads By"
                  value={s.latest_correction_factor
                    ? `${((1 / s.latest_correction_factor - 1) * 100).toFixed(1)}%`
                    : "—"}
                  sub="vs UHBVN meter (latest)"
                  color="text-amber-400"
                />
                <MiniStat
                  label="Avg Solar Offset"
                  value={s.avg_solar_offset_pct != null ? `${s.avg_solar_offset_pct.toFixed(0)}%` : "—"}
                  sub="of consumption from solar"
                  color="text-blue-400"
                />
                <MiniStat
                  label="Avg Self-Consumed"
                  value={s.avg_self_consumption_pct != null ? `${s.avg_self_consumption_pct.toFixed(0)}%` : "—"}
                  sub="of solar used in-house"
                  color="text-purple-400"
                />
              </div>

              <div className="text-xs px-3 py-2 rounded-lg border border-blue-500/20 bg-blue-500/5 flex items-start gap-2" style={{ color: "var(--card-sub)" }}>
                <Info className="w-3.5 h-3.5 text-blue-400 mt-0.5 flex-shrink-0" />
                <span>
                  Shinemonitor reads the inverter&apos;s internal counter which over-reports vs the UHBVN physical KWHS meter.
                  The correction factor is automatically updated each time you add a bill.
                  {s.bills_with_meter_comparison < 3 && " Add more bills for a more stable average."}
                </span>
              </div>
            </div>
          )}

          {/* ── Per-bill breakdown ── */}
          <div className="glass-card rounded-2xl p-5 space-y-4">
            <h3 className="text-sm font-semibold" style={{ color: "var(--card-value)" }}>Per-Bill Analysis</h3>
            <div className="space-y-4">
              {[...bills].reverse().map((b, i) => {
                const hasComparison = b.solar_kwh_app != null && b.solar_kwh_bill != null;
                return (
                  <div key={i} className="rounded-xl border p-4 space-y-3" style={{ borderColor: "var(--bg-border)", background: "var(--bg-surface-2)" }}>
                    {/* Period header */}
                    <div className="flex items-center justify-between flex-wrap gap-2">
                      <div className="flex items-center gap-2">
                        <Calendar className="w-3.5 h-3.5 text-slate-400" />
                        <span className="text-sm font-medium" style={{ color: "var(--card-value)" }}>
                          {periodLabel(b.period_from, b.period_to)}
                        </span>
                      </div>
                      <div className="flex items-center gap-3 text-xs">
                        {b.amount_inr != null && (
                          <span className={b.amount_inr < 0 ? "text-emerald-400" : "text-amber-400"}>
                            ₹{b.amount_inr.toFixed(0)}{b.amount_inr < 0 ? " credit" : ""}
                          </span>
                        )}
                        {b.carry_forward_kwh != null && b.carry_forward_kwh > 0 && (
                          <span className="text-blue-400">{b.carry_forward_kwh.toFixed(0)} kWh c/f</span>
                        )}
                      </div>
                    </div>

                    {/* Energy flow row */}
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
                      <div>
                        <div className="text-amber-400 font-semibold">{b.solar_kwh_bill?.toFixed(0) ?? "—"} kWh</div>
                        <div style={{ color: "var(--card-sub)" }}>Solar (KWHS meter)</div>
                      </div>
                      <div>
                        <div className="text-blue-400 font-semibold">{b.import_kwh?.toFixed(0) ?? "—"} kWh</div>
                        <div style={{ color: "var(--card-sub)" }}>Grid import (KWHI)</div>
                      </div>
                      <div>
                        <div className="text-emerald-400 font-semibold">{b.export_kwh?.toFixed(0) ?? "—"} kWh</div>
                        <div style={{ color: "var(--card-sub)" }}>Grid export (KWHE)</div>
                      </div>
                      <div>
                        <div className="font-semibold" style={{ color: "var(--card-value)" }}>{b.total_consumption_kwh?.toFixed(0) ?? "—"} kWh</div>
                        <div style={{ color: "var(--card-sub)" }}>Total household use</div>
                      </div>
                    </div>

                    {/* Shinemonitor vs meter comparison */}
                    {hasComparison ? (
                      <div className="flex flex-wrap gap-4 text-xs pt-1 border-t" style={{ borderColor: "var(--bg-border)" }}>
                        <div>
                          <span style={{ color: "var(--card-sub)" }}>App (Shinemonitor): </span>
                          <span className="font-medium" style={{ color: "var(--card-value)" }}>{b.solar_kwh_app?.toFixed(1)} kWh</span>
                        </div>
                        <div>
                          <span style={{ color: "var(--card-sub)" }}>UHBVN meter: </span>
                          <span className="font-medium" style={{ color: "var(--card-value)" }}>{b.solar_kwh_bill?.toFixed(1)} kWh</span>
                        </div>
                        <div>
                          <span style={{ color: "var(--card-sub)" }}>Discrepancy: </span>
                          <span className={`font-semibold ${(b.over_read_pct ?? 0) > 10 ? "text-amber-400" : "text-emerald-400"}`}>
                            +{b.over_read_pct?.toFixed(1)}% app over-reads
                          </span>
                        </div>
                        {b.meter_correction != null && (
                          <div>
                            <span style={{ color: "var(--card-sub)" }}>Factor: </span>
                            <span className="font-medium text-blue-400">{b.meter_correction.toFixed(4)}</span>
                          </div>
                        )}
                      </div>
                    ) : (
                      <div className="text-xs pt-1 border-t" style={{ borderColor: "var(--bg-border)", color: "var(--card-sub)" }}>
                        Shinemonitor vs UHBVN comparison not available for this period
                        {!b.solar_kwh_bill && " — solar kWh not recorded in bill"}
                      </div>
                    )}

                    {/* Ratios */}
                    {(b.self_consumption_pct != null || b.solar_offset_pct != null) && (
                      <div className="flex gap-4 text-xs">
                        {b.self_consumption_pct != null && (
                          <div>
                            <span style={{ color: "var(--card-sub)" }}>Self-consumed: </span>
                            <span className="font-medium text-purple-400">{b.self_consumption_pct.toFixed(0)}% of solar</span>
                          </div>
                        )}
                        {b.solar_offset_pct != null && (
                          <div>
                            <span style={{ color: "var(--card-sub)" }}>Solar offset: </span>
                            <span className="font-medium text-blue-400">{b.solar_offset_pct.toFixed(0)}% of consumption</span>
                          </div>
                        )}
                      </div>
                    )}

                    {/* Anomalies & billing flags */}
                    {b.anomalies.length > 0 && (
                      <div className="space-y-2 pt-1 border-t" style={{ borderColor: "var(--bg-border)" }}>
                        {b.anomalies.map((a, j) => {
                          const isError   = a.level === "error";
                          const isWarning = a.level === "warning";
                          const borderCls = isError ? "border-red-500/30 bg-red-500/5" : isWarning ? "border-amber-500/30 bg-amber-500/5" : "border-blue-500/20 bg-blue-500/5";
                          const iconCls   = isError ? "text-red-400" : isWarning ? "text-amber-400" : "text-blue-400";
                          const Icon      = isError ? AlertCircle : isWarning ? AlertTriangle : Info;
                          return (
                            <div key={j} className={`rounded-lg border p-3 space-y-1 ${borderCls}`}>
                              <div className={`flex items-start gap-2 text-xs font-semibold ${iconCls}`}>
                                <Icon className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
                                {a.title}
                              </div>
                              <p className="text-xs pl-5" style={{ color: "var(--card-sub)" }}>{a.detail}</p>
                              {a.action && (
                                <p className={`text-xs pl-5 font-medium ${iconCls}`}>→ {a.action}</p>
                              )}
                            </div>
                          );
                        })}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        </div>
      )}

      {/* ── Empty state when no bills yet ── */}
      {bills.length === 0 && !insightsLoading && stage === "idle" && (
        <div className="glass-card rounded-2xl p-8 text-center space-y-2">
          <TrendingUp className="w-8 h-8 text-slate-500 mx-auto" />
          <p className="text-sm font-medium" style={{ color: "var(--card-value)" }}>No bills stored yet</p>
          <p className="text-xs" style={{ color: "var(--card-sub)" }}>
            Upload your first UHBVN bill above. Each bill teaches the app your actual consumption pattern
            and calibrates the Shinemonitor vs UHBVN meter discrepancy.
          </p>
        </div>
      )}

    </div>
  );
}
