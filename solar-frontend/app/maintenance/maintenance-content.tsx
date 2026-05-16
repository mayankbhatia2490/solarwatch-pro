"use client";

import { useState, useEffect } from "react";
import { Calendar, Droplets, Loader2, AlertTriangle, TrendingUp } from "lucide-react";
import { CleaningCalendar } from "@/components/cleaning-calendar";

export default function MaintenanceContent() {
  const [data, setData]         = useState<any>(null);
  const [cleaning, setCleaning] = useState<any>(null);
  const [loading, setLoading]   = useState(true);

  const [logDate, setLogDate]   = useState(() => new Date().toISOString().slice(0, 10));
  const [logNotes, setLogNotes] = useState("");
  const [logType, setLogType]   = useState<"manual" | "rain">("manual");
  const [logSaving, setLogSaving] = useState(false);
  const [logMsg, setLogMsg]     = useState("");

  async function fetchAll() {
    const API = process.env.NEXT_PUBLIC_API_URL ?? "";
    const [mRes, cRes] = await Promise.all([
      fetch(`${API}/api/maintenance`).catch(() => null),
      fetch(`${API}/api/cleaning`).catch(() => null),
    ]);
    if (mRes?.ok) setData((await mRes.json()).data);
    if (cRes?.ok) setCleaning(await cRes.json());
    setLoading(false);
  }

  useEffect(() => { fetchAll(); }, []);

  async function submitCleaning() {
    setLogSaving(true);
    setLogMsg("");
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL ?? ""}/api/cleaning`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ date: logDate, notes: logNotes, type: logType }),
      });
      if (!res.ok) throw new Error(await res.text());
      setLogMsg("Saved! Efficiency impact will appear after 7 days of data.");
      setLogNotes("");
      await fetchAll();
    } catch (e: any) {
      setLogMsg(`Error: ${e.message}`);
    } finally {
      setLogSaving(false);
    }
  }

  if (loading) return (
    <div className="flex items-center justify-center h-64">
      <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-emerald-400" />
    </div>
  );

  return (
    <div className="space-y-6">

      {/* Cleaning status banner */}
      {cleaning && (
        <div className={`themed-card p-4 border-l-4 flex items-center gap-4 flex-wrap ${
          cleaning.urgency === "high"   ? "border-l-red-500" :
          cleaning.urgency === "medium" ? "border-l-amber-500" : "border-l-emerald-500"
        }`}>
          <Droplets className={`w-5 h-5 flex-shrink-0 ${
            cleaning.urgency === "high" ? "text-red-500" :
            cleaning.urgency === "medium" ? "text-amber-500" : "text-emerald-500"
          }`} />
          <div className="flex-1 min-w-0">
            <div className="font-semibold text-sm" style={{ color: "var(--card-value)" }}>
              {cleaning.urgency === "high" ? "Clean panels now" :
               cleaning.urgency === "medium" ? "Cleaning recommended soon" :
               "Panels looking clean"}
            </div>
            <div className="text-xs mt-0.5" style={{ color: "var(--text-secondary)" }}>
              {cleaning.days_since_cleaning} days since last clean
              {cleaning.current_efficiency_pct != null &&
                ` · Current efficiency: ${cleaning.current_efficiency_pct}%`}
            </div>
          </div>
          {data && (
            <div className="text-right">
              <div className="text-xs" style={{ color: "var(--text-secondary)" }}>Next Service</div>
              <div className="font-bold text-emerald-400 flex items-center gap-1">
                <Calendar className="w-4 h-4" />
                {data.days_to_service} days
              </div>
            </div>
          )}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">

        {/* Left: Calendar + log form */}
        <div className="space-y-4">
          <CleaningCalendar />

          {/* Quick log form */}
          <div className="themed-card p-5">
            <h2 className="text-base font-bold mb-3" style={{ color: "var(--card-value)" }}>
              Log a Cleaning
            </h2>
            <div className="space-y-3">
              <div className="flex gap-3">
                <div className="flex-1">
                  <label className="text-xs font-medium block mb-1" style={{ color: "var(--card-label)" }}>Date</label>
                  <input
                    type="date"
                    value={logDate}
                    max={new Date().toISOString().slice(0, 10)}
                    onChange={e => setLogDate(e.target.value)}
                    className="w-full px-3 py-2 rounded-lg text-sm border outline-none focus:border-emerald-500"
                    style={{ background: "var(--bg-surface)", color: "var(--card-value)", borderColor: "var(--bg-border)" }}
                  />
                </div>
                <div>
                  <label className="text-xs font-medium block mb-1" style={{ color: "var(--card-label)" }}>Type</label>
                  <div className="flex gap-1.5 h-[38px] items-center">
                    {(["manual", "rain"] as const).map(t => (
                      <button key={t} onClick={() => setLogType(t)}
                        className={`px-3 py-1.5 rounded-lg text-xs font-medium border transition-colors ${
                          logType === t
                            ? "bg-emerald-500/20 border-emerald-500/50 text-emerald-500"
                            : "border-[var(--bg-border)] text-[var(--text-secondary)]"
                        }`}>
                        {t === "manual" ? "🧹 Manual" : "🌧️ Rain"}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
              <div>
                <label className="text-xs font-medium block mb-1" style={{ color: "var(--card-label)" }}>Notes</label>
                <input
                  type="text"
                  value={logNotes}
                  onChange={e => setLogNotes(e.target.value)}
                  placeholder="e.g. Full wash with water + brush, 8am"
                  className="w-full px-3 py-2 rounded-lg text-sm border outline-none focus:border-emerald-500"
                  style={{ background: "var(--bg-surface)", color: "var(--card-value)", borderColor: "var(--bg-border)" }}
                />
              </div>
              {logMsg && (
                <p className={`text-xs ${logMsg.startsWith("Error") ? "text-red-400" : "text-emerald-400"}`}>{logMsg}</p>
              )}
              <button onClick={submitCleaning} disabled={logSaving}
                className="w-full py-2.5 rounded-lg bg-emerald-500 hover:bg-emerald-600 text-white text-sm font-semibold transition-colors disabled:opacity-60 flex items-center justify-center gap-2">
                {logSaving && <Loader2 className="w-4 h-4 animate-spin" />}
                {logSaving ? "Saving…" : "Save Cleaning Event"}
              </button>
            </div>
          </div>
        </div>

        {/* Right: Cleaning history + service predictions */}
        <div className="space-y-4">

          {/* Cleaning history */}
          {cleaning?.history?.length > 0 && (
            <div className="themed-card p-5">
              <h2 className="text-base font-bold mb-3" style={{ color: "var(--card-value)" }}>
                Cleaning History
              </h2>
              <div className="space-y-3">
                {cleaning.history.slice(0, 6).map((ev: any, i: number) => (
                  <div key={i} className="flex items-start gap-3 py-2 border-b last:border-0"
                    style={{ borderColor: "var(--bg-border)" }}>
                    <span className="text-base leading-none mt-0.5">
                      {ev.type === "rain" ? "🌧️" : "🧹"}
                    </span>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center justify-between gap-2">
                        <span className="font-mono text-xs font-semibold" style={{ color: "var(--card-value)" }}>
                          {ev.date}
                        </span>
                        {ev.efficiency_gain_pct != null && (
                          <span className={`text-xs font-semibold flex items-center gap-0.5 ${ev.efficiency_gain_pct >= 0 ? "text-emerald-500" : "text-red-400"}`}>
                            <TrendingUp className="w-3 h-3" />
                            {ev.efficiency_gain_pct >= 0 ? "+" : ""}{ev.efficiency_gain_pct}%
                          </span>
                        )}
                      </div>
                      {ev.notes && (
                        <div className="text-xs mt-0.5 truncate" style={{ color: "var(--text-secondary)" }}>{ev.notes}</div>
                      )}
                      {ev.efficiency_before_pct != null && (
                        <div className="text-xs mt-0.5" style={{ color: "var(--text-muted)" }}>
                          {ev.efficiency_before_pct}% → {ev.efficiency_after_pct ?? "…"}%
                        </div>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* Service predictions */}
          {data?.predictions?.length > 0 && (
            <div className="space-y-3">
              <h2 className="text-base font-bold" style={{ color: "var(--card-value)" }}>Active Predictions</h2>
              {data.predictions.map((pred: any) => (
                <div key={pred.id} className="themed-card p-4 border-l-4 border-l-amber-500">
                  <div className="flex justify-between items-start mb-2">
                    <h3 className="font-bold text-sm flex items-center gap-2">
                      <AlertTriangle className="w-4 h-4 text-amber-500" />
                      {pred.title}
                    </h3>
                    <span className="text-xs px-2 py-0.5 bg-amber-500/10 text-amber-500 rounded-full font-medium">
                      {pred.confidence}% confident
                    </span>
                  </div>
                  <p className="text-xs mb-3" style={{ color: "var(--text-secondary)" }}>{pred.trend}</p>
                  <div className="rounded-xl p-3 grid grid-cols-2 gap-3 mb-3 text-xs" style={{ background: "var(--bg-hover)" }}>
                    <div>
                      <div className="text-[var(--text-muted)] text-xs">Fix cost</div>
                      <div className="font-semibold text-red-400">₹{pred.fix_cost_inr}</div>
                    </div>
                    <div>
                      <div className="text-[var(--text-muted)] text-xs">Monthly savings</div>
                      <div className="font-semibold text-emerald-400">₹{pred.revenue_saved_inr}</div>
                    </div>
                  </div>
                  <button className="w-full py-2 rounded-lg text-sm font-semibold border transition-colors hover:bg-[var(--bg-hover)]"
                    style={{ borderColor: "var(--bg-border)", color: "var(--text-primary)" }}>
                    {pred.action}
                  </button>
                </div>
              ))}
            </div>
          )}

          {/* Service history timeline */}
          {data?.history?.length > 0 && (
            <div className="themed-card p-5 relative">
              <h2 className="text-base font-bold mb-4" style={{ color: "var(--card-value)" }}>Service History</h2>
              <div className="absolute left-9 top-12 bottom-8 w-0.5" style={{ background: "var(--bg-border)" }} />
              <div className="space-y-5">
                {data.history.map((hist: any, i: number) => (
                  <div key={i} className="relative flex gap-4">
                    <div className="w-6 h-6 rounded-full border-2 border-emerald-500 flex-shrink-0 z-10"
                      style={{ background: "var(--bg-base)" }} />
                    <div>
                      <div className="text-xs" style={{ color: "var(--text-muted)" }}>
                        {new Date(hist.date).toLocaleDateString()}
                      </div>
                      <div className="font-semibold text-sm mt-0.5" style={{ color: "var(--card-value)" }}>{hist.action}</div>
                      <div className="text-xs mt-0.5 flex items-center gap-1" style={{ color: "var(--text-secondary)" }}>
                        <TrendingUp className="w-3 h-3" /> {hist.outcome}
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
