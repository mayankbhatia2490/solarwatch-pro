"use client";

import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { useTheme } from "next-themes";
import { AlertTriangle, CheckCircle, Info, Calendar, Droplets, TrendingUp, TrendingDown, Sparkles, Loader2 } from "lucide-react";

// Lightweight inline markdown renderer — handles ### headers and - bullets only
function AiReport({ text }: { text: string }) {
  const lines = text.split("\n");
  return (
    <div className="space-y-1 text-sm leading-relaxed" style={{ color: "var(--text-secondary)" }}>
      {lines.map((line, i) => {
        if (line.startsWith("### ")) {
          return (
            <div key={i} className="font-bold text-base pt-3 first:pt-0" style={{ color: "var(--card-value)" }}>
              {line.replace("### ", "")}
            </div>
          );
        }
        if (line.startsWith("## ")) {
          return (
            <div key={i} className="font-bold text-lg pt-3 first:pt-0" style={{ color: "var(--card-value)" }}>
              {line.replace("## ", "")}
            </div>
          );
        }
        if (line.match(/^[-*] /)) {
          return (
            <div key={i} className="flex gap-2 ml-2">
              <span className="text-emerald-500 flex-shrink-0">•</span>
              <span>{line.replace(/^[-*] /, "")}</span>
            </div>
          );
        }
        if (line.trim() === "") return <div key={i} className="h-1" />;
        return <div key={i}>{line}</div>;
      })}
    </div>
  );
}

const Chart = dynamic(() => import("react-apexcharts"), { ssr: false });

const PERIOD_OPTIONS = [
  { label: "7d",  value: 7  },
  { label: "14d", value: 14 },
  { label: "30d", value: 30 },
  { label: "60d", value: 60 },
  { label: "90d", value: 90 },
];

function PriorityIcon({ priority }: { priority: string }) {
  if (priority === "good")     return <CheckCircle className="w-5 h-5 text-emerald-500" />;
  if (priority === "warning")  return <AlertTriangle className="w-5 h-5 text-amber-500" />;
  if (priority === "critical") return <AlertTriangle className="w-5 h-5 text-red-500" />;
  return <Info className="w-5 h-5 text-blue-400" />;
}

function borderColor(priority: string) {
  if (priority === "good")     return "border-l-emerald-500";
  if (priority === "warning")  return "border-l-amber-500";
  if (priority === "critical") return "border-l-red-500";
  return "border-l-blue-400";
}

export default function AnalysisPage() {
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === "dark";
  const [data, setData]           = useState<any>(null);
  const [cleaning, setCleaning]   = useState<any[]>([]);
  const [loading, setLoading]     = useState(true);
  const [days, setDays]           = useState(30);
  const [aiReport, setAiReport]   = useState<string | null>(null);
  const [aiLoading, setAiLoading] = useState(false);
  const [aiError, setAiError]     = useState<string | null>(null);
  const [aiDays, setAiDays]       = useState(0);  // which period was last analysed

  useEffect(() => {
    setLoading(true);
    // Reset AI report when period changes
    setAiReport(null);
    setAiError(null);
    const API = process.env.NEXT_PUBLIC_API_URL ?? "";
    Promise.all([
      fetch(`${API}/api/analysis?days=${days}`).then(r => r.ok ? r.json() : null),
      fetch(`${API}/api/cleaning`).then(r => r.ok ? r.json() : { history: [] }),
    ]).then(([analysis, clean]) => {
      setData(analysis);
      setCleaning(clean?.history ?? []);
      setLoading(false);
    }).catch(() => setLoading(false));
  }, [days]);

  async function generateAiReport() {
    setAiLoading(true);
    setAiError(null);
    setAiReport(null);
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL ?? ""}/api/ai/insight?days=${days}`);
      const json = await res.json();
      if (!res.ok) {
        setAiError(json.detail || "Failed to generate AI report");
      } else {
        setAiReport(json.ai_report);
        setAiDays(json.period_days);
      }
    } catch {
      setAiError("Could not reach the API — check your connection.");
    } finally {
      setAiLoading(false);
    }
  }

  const labelColor = isDark ? "#94a3b8" : "#475569";
  const gridColor  = isDark ? "rgba(148,163,184,0.1)" : "#e2e8f0";

  // Cleaning annotations for the daily chart (vertical red dashed lines)
  const cleaningAnnotations = cleaning.map((ev: any) => ({
    x: ev.date,
    borderColor: "#a78bfa",
    strokeDashArray: 4,
    label: {
      text: "🧹 Cleaned",
      style: { color: "#fff", background: "#7c3aed", fontSize: "10px" },
      orientation: "vertical",
    },
  }));

  // ── Daily bar chart ───────────────────────────────────────────────────────
  const barSeries = data ? [
    { name: "Expected (weather)", data: data.daily_bars.map((d: any) => d.expected_kwh) },
    { name: "Actual output",      data: data.daily_bars.map((d: any) => d.actual_kwh)   },
  ] : [];

  const barOptions: any = {
    chart: { type: "bar", background: "transparent", toolbar: { show: false }, animations: { enabled: false } },
    theme: { mode: isDark ? "dark" : "light" },
    colors: ["#3b82f6", "#22c55e"],
    plotOptions: { bar: { columnWidth: "70%", borderRadius: 3 } },
    dataLabels: { enabled: false },
    xaxis: {
      categories: data?.daily_bars.map((d: any) => d.date.slice(5)) ?? [],
      labels: { style: { colors: labelColor }, rotate: -45 },
      axisBorder: { show: false }, axisTicks: { show: false },
    },
    yaxis: { labels: { style: { colors: labelColor }, formatter: (v: number) => `${v.toFixed(1)}` }, title: { text: "kWh", style: { color: labelColor } } },
    grid: { borderColor: gridColor, strokeDashArray: 4 },
    tooltip: { theme: isDark ? "dark" : "light", y: { formatter: (v: number) => `${v.toFixed(2)} kWh` } },
    legend: { labels: { colors: isDark ? "#f1f5f9" : "#334155" }, position: "top", horizontalAlign: "right" },
    annotations: { xaxis: cleaningAnnotations },
  };

  // ── PR trend line chart ───────────────────────────────────────────────────
  const prSeries = data ? [
    { name: "7-day rolling PR %", data: data.pr_trend.map((d: any) => ({ x: new Date(d.date).getTime(), y: d.pr_7d })) },
  ] : [];

  const prCleanAnnotations = cleaning.map((ev: any) => ({
    x: new Date(ev.date).getTime(),
    borderColor: "#7c3aed",
    strokeDashArray: 4,
    label: { text: "🧹", style: { color: "#fff", background: "#7c3aed", fontSize: "11px" } },
  }));

  const prOptions: any = {
    chart: { type: "line", background: "transparent", toolbar: { show: false }, animations: { enabled: false } },
    theme: { mode: isDark ? "dark" : "light" },
    colors: ["#22c55e"],
    stroke: { curve: "smooth", width: 2.5 },
    xaxis: { type: "datetime", labels: { style: { colors: labelColor }, datetimeUTC: false }, axisBorder: { show: false }, axisTicks: { show: false } },
    yaxis: { min: 40, max: 110, labels: { style: { colors: labelColor }, formatter: (v: number) => `${v.toFixed(0)}%` }, title: { text: "PR %", style: { color: labelColor } } },
    grid: { borderColor: gridColor, strokeDashArray: 4 },
    tooltip: { theme: isDark ? "dark" : "light", y: { formatter: (v: number) => `${v?.toFixed(1)}%` } },
    annotations: {
      yaxis: [{ y: 78, borderColor: "#f59e0b", strokeDashArray: 5, label: { text: "Baseline 78%", style: { color: "#000", background: "#f59e0b" } } }],
      xaxis: prCleanAnnotations,
    },
  };

  // ── Hour profile bar chart ────────────────────────────────────────────────
  const hourSeries = data ? [
    { name: "Expected", data: data.hourly_profile.map((h: any) => h.avg_expected_w) },
    { name: "Actual",   data: data.hourly_profile.map((h: any) => h.avg_actual_w)   },
  ] : [];

  const hourOptions: any = {
    chart: { type: "bar", background: "transparent", toolbar: { show: false }, animations: { enabled: false } },
    theme: { mode: isDark ? "dark" : "light" },
    colors: ["#3b82f6", "#22c55e"],
    plotOptions: { bar: { columnWidth: "75%", borderRadius: 2 } },
    dataLabels: { enabled: false },
    xaxis: {
      categories: data?.hourly_profile.map((h: any) => h.label) ?? [],
      labels: { style: { colors: labelColor } },
      axisBorder: { show: false }, axisTicks: { show: false },
    },
    yaxis: { labels: { style: { colors: labelColor }, formatter: (v: number) => `${(v/1000).toFixed(1)}kW` } },
    grid: { borderColor: gridColor, strokeDashArray: 4 },
    tooltip: { theme: isDark ? "dark" : "light", y: { formatter: (v: number) => `${v.toFixed(0)} W` } },
    legend: { labels: { colors: isDark ? "#f1f5f9" : "#334155" }, position: "top", horizontalAlign: "right" },
  };

  if (loading) return (
    <div className="flex items-center justify-center h-64">
      <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-emerald-400" />
    </div>
  );

  if (!data) return (
    <div className="themed-card p-8 text-center space-y-2">
      <div className="text-2xl">📡</div>
      <div className="font-semibold" style={{ color: "var(--card-value)" }}>Could not reach the API</div>
      <div className="text-sm" style={{ color: "var(--text-secondary)" }}>
        Check that <code className="px-1 bg-black/20 rounded">solar-api</code> is running — or visit{" "}
        <span className="text-emerald-500">/api/analysis</span> directly to see the error.
      </div>
    </div>
  );

  const s = data.summary;
  const prVsDesign = s.overall_pr_pct - s.design_pr_pct;
  const prColor = prVsDesign >= 0 ? "text-emerald-500" : prVsDesign >= -8 ? "text-amber-500" : "text-red-500";

  // ── Generation donut chart ────────────────────────────────────────────────
  const lostKwh = Math.max(s.total_expected_kwh - s.total_actual_kwh, 0);
  const donutSeries = [s.total_actual_kwh, lostKwh > 0 ? lostKwh : 0];
  const donutOptions: any = {
    chart: { type: "donut", background: "transparent" },
    theme: { mode: isDark ? "dark" : "light" },
    labels: ["Actual generated", "Unrealised (gap)"],
    colors: ["#22c55e", "#f59e0b"],
    dataLabels: { enabled: false },
    legend: { labels: { colors: isDark ? "#f1f5f9" : "#334155" }, position: "bottom" },
    plotOptions: { pie: { donut: { size: "65%",
      labels: { show: true, total: {
        show: true, label: "PR",
        formatter: () => `${s.overall_pr_pct}%`,
        color: isDark ? "#f1f5f9" : "#334155",
      }},
    }}},
    tooltip: { y: { formatter: (v: number) => `${v.toFixed(1)} kWh` } },
  };

  return (
    <div className="space-y-6 max-w-6xl mx-auto">

      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-3xl font-bold" style={{ color: "var(--card-value)" }}>System Performance Analysis</h1>
          <p style={{ color: "var(--text-secondary)" }} className="mt-1 text-sm">
            Actual vs weather-adjusted expected · KSY 3.4kW-1Ph · Karnal · Purple lines = panel cleaning dates
          </p>
        </div>
        <div className="flex items-center gap-2 flex-wrap">
          <Calendar className="w-4 h-4" style={{ color: "var(--text-muted)" }} />
          {PERIOD_OPTIONS.map(o => (
            <button key={o.value} onClick={() => setDays(o.value)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${days === o.value ? "bg-emerald-500 text-white" : "themed-card text-[var(--text-secondary)] hover:text-[var(--text-primary)]"}`}>
              {o.label}
            </button>
          ))}
        </div>
      </div>

      {/* KPI Summary cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="themed-card p-5">
          <div className="text-xs mb-1" style={{ color: "var(--card-label)" }}>Performance Ratio</div>
          <div className={`text-3xl font-black ${prColor}`}>{s.overall_pr_pct}%</div>
          <div className="text-xs mt-1" style={{ color: "var(--card-sub)" }}>
            {prVsDesign >= 0 ? "+" : ""}{prVsDesign.toFixed(1)}% vs {s.design_pr_pct}% India baseline
          </div>
        </div>
        <div className="themed-card p-5">
          <div className="text-xs mb-1" style={{ color: "var(--card-label)" }}>Weather-Expected</div>
          <div className="text-3xl font-black number-gradient-blue">{s.total_expected_kwh} kWh</div>
          <div className="text-xs mt-1" style={{ color: "var(--card-sub)" }}>Based on real irradiance</div>
        </div>
        <div className="themed-card p-5">
          <div className="text-xs mb-1" style={{ color: "var(--card-label)" }}>Actually Generated</div>
          <div className="text-3xl font-black number-gradient">{s.total_actual_kwh} kWh</div>
          <div className="text-xs mt-1" style={{ color: "var(--card-sub)" }}>Measured by inverter</div>
        </div>
        <div className="themed-card p-5">
          <div className="text-xs mb-1" style={{ color: "var(--card-label)" }}>Generation Gap</div>
          <div className={`text-3xl font-black ${s.lost_kwh > 5 ? "text-amber-500" : "text-emerald-500"}`}>
            {s.lost_kwh > 0 ? `${s.lost_kwh} kWh` : "None"}
          </div>
          <div className="text-xs mt-1" style={{ color: "var(--card-sub)" }}>
            {s.lost_kwh > 0 ? `≈ ₹${s.lost_inr} · ${s.underperform_days}/${s.total_days} days` : "All generation within expected"}
          </div>
        </div>
      </div>

      {/* Generation breakdown donut + stats */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="themed-card p-5">
          <h2 className="text-base font-semibold mb-3" style={{ color: "var(--card-title)" }}>
            Generation Breakdown
          </h2>
          <div className="h-[220px]">
            <Chart options={donutOptions} series={donutSeries} type="donut" height="100%" />
          </div>
        </div>
        <div className="themed-card p-5 space-y-3">
          <h2 className="text-base font-semibold mb-1" style={{ color: "var(--card-title)" }}>Period Summary</h2>
          {[
            { label: "Period",           value: `${days} days` },
            { label: "Weather-expected", value: `${s.total_expected_kwh} kWh` },
            { label: "Actually generated", value: `${s.total_actual_kwh} kWh`, highlight: true },
            { label: "Unrealised generation", value: lostKwh > 0 ? `${lostKwh.toFixed(1)} kWh (≈ ₹${s.lost_inr})` : "None ✓" },
            { label: "Performance Ratio", value: `${s.overall_pr_pct}%` },
            { label: "Under-performing days", value: `${s.underperform_days} / ${s.total_days}` },
          ].map(({ label, value, highlight }) => (
            <div key={label} className="flex items-center justify-between py-2 border-b last:border-0 text-sm"
              style={{ borderColor: "var(--bg-border)" }}>
              <span style={{ color: "var(--card-label)" }}>{label}</span>
              <span className={`font-semibold ${highlight ? "text-emerald-500" : ""}`}
                style={highlight ? {} : { color: "var(--card-value)" }}>{value}</span>
            </div>
          ))}
        </div>
      </div>

      {/* Recommendations */}
      <div className="space-y-3">
        <h2 className="text-lg font-semibold" style={{ color: "var(--card-title)" }}>What this means + what to do</h2>
        {(data.recommendations || []).map((r: any, i: number) => (
          <div key={i} className={`themed-card p-4 border-l-4 ${borderColor(r.priority)}`}>
            <div className="flex items-start gap-3">
              <PriorityIcon priority={r.priority} />
              <div className="flex-1">
                <div className="font-semibold text-sm" style={{ color: "var(--card-value)" }}>{r.icon} {r.title}</div>
                <div className="text-sm mt-1" style={{ color: "var(--text-secondary)" }}>{r.detail}</div>
                <div className="mt-2 text-xs font-medium px-2 py-1 rounded-lg inline-block bg-emerald-500/10 text-emerald-600">
                  → {r.action}
                </div>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* AI Insight panel */}
      <div className="themed-card p-6">
        <div className="flex items-center justify-between gap-4 flex-wrap">
          <div className="flex items-center gap-2">
            <Sparkles className="w-5 h-5 text-violet-400" />
            <div>
              <h2 className="text-lg font-semibold leading-tight" style={{ color: "var(--card-title)" }}>
                AI Diagnostic Report
              </h2>
              <p className="text-xs mt-0.5" style={{ color: "var(--card-sub)" }}>
                Gemini 1.5 Flash · powered by real sensor data · free tier
              </p>
            </div>
          </div>
          <button
            onClick={generateAiReport}
            disabled={aiLoading}
            className="flex items-center gap-2 px-4 py-2 rounded-xl bg-violet-500 hover:bg-violet-600 text-white text-sm font-semibold transition-colors disabled:opacity-60"
          >
            {aiLoading
              ? <><Loader2 className="w-4 h-4 animate-spin" /> Analysing {days}-day data…</>
              : <><Sparkles className="w-4 h-4" /> {aiReport ? "Regenerate" : "Generate Analysis"}</>
            }
          </button>
        </div>

        {!aiReport && !aiLoading && !aiError && (
          <p className="mt-4 text-sm" style={{ color: "var(--text-secondary)" }}>
            Click <strong style={{ color: "var(--card-value)" }}>Generate Analysis</strong> to get an AI-written diagnostic report
            for this {days}-day period — covering your PR trend, thermal derating, shading patterns,
            cleaning impact, and priority actions. Uses your real inverter data, not generic advice.
          </p>
        )}

        {aiLoading && (
          <div className="mt-4 flex items-center gap-3 py-6 justify-center">
            <Loader2 className="w-6 h-6 animate-spin text-violet-400" />
            <span className="text-sm" style={{ color: "var(--text-secondary)" }}>
              Fetching {days} days of sensor data and sending to Gemini…
            </span>
          </div>
        )}

        {aiError && (
          <div className="mt-4 rounded-xl border border-red-500/30 bg-red-500/10 p-4">
            <p className="text-sm text-red-400 font-medium">Could not generate report</p>
            <p className="text-xs mt-1 text-red-300">{aiError}</p>
            {aiError.includes("GEMINI_API_KEY") && (
              <p className="text-xs mt-2" style={{ color: "var(--text-secondary)" }}>
                Add <code className="bg-black/20 px-1 rounded">GEMINI_API_KEY=your_key</code> to
                your <code className="bg-black/20 px-1 rounded">.env</code> file and rebuild solar-api.
                Get a free key at{" "}
                <span className="text-violet-400">aistudio.google.com/app/apikey</span>
              </p>
            )}
          </div>
        )}

        {aiReport && (
          <div className="mt-5 pt-5 border-t" style={{ borderColor: "var(--bg-border)" }}>
            <div className="flex items-center justify-between mb-3">
              <span className="text-xs px-2 py-0.5 rounded-full bg-violet-500/15 text-violet-400 font-medium">
                Gemini 1.5 Flash · {aiDays}-day analysis
              </span>
              <span className="text-xs" style={{ color: "var(--text-muted)" }}>
                Based on real InfluxDB readings — not fabricated
              </span>
            </div>
            <AiReport text={aiReport} />
          </div>
        )}
      </div>

      {/* Daily bar chart */}
      <div className="themed-card p-6">
        <h2 className="text-lg font-semibold mb-1" style={{ color: "var(--card-title)" }}>
          Daily: Actual vs Weather-Expected
        </h2>
        <p className="text-xs mb-4" style={{ color: "var(--card-sub)" }}>
          🔵 Blue = what irradiance says you should produce · 🟢 Green = inverter actual · 🟣 Purple lines = panel cleaning
        </p>
        {data.daily_bars.length === 0 ? (
          <div className="h-40 flex items-center justify-center text-sm" style={{ color: "var(--card-sub)" }}>
            No daytime data yet — data appears after a sunny day.
          </div>
        ) : (
          <div className="h-[300px]">
            <Chart options={barOptions} series={barSeries} type="bar" height="100%" />
          </div>
        )}
      </div>

      {/* PR trend */}
      <div className="themed-card p-6">
        <h2 className="text-lg font-semibold mb-1" style={{ color: "var(--card-title)" }}>
          Performance Ratio Trend (7-day rolling)
        </h2>
        <p className="text-xs mb-4" style={{ color: "var(--card-sub)" }}>
          Dipping below amber line (78%) means something is reducing efficiency. 🟣 Purple = cleaning — look for a PR jump after each clean.
        </p>
        {data.pr_trend.length < 2 ? (
          <div className="h-40 flex items-center justify-center text-sm" style={{ color: "var(--card-sub)" }}>
            Need at least 7 days of data for this chart.
          </div>
        ) : (
          <div className="h-[240px]">
            <Chart options={prOptions} series={prSeries} type="line" height="100%" />
          </div>
        )}
      </div>

      {/* Cleaning correlation table */}
      {cleaning.length > 0 && (
        <div className="themed-card p-6">
          <div className="flex items-center gap-2 mb-4">
            <Droplets className="w-5 h-5 text-violet-400" />
            <h2 className="text-lg font-semibold" style={{ color: "var(--card-title)" }}>
              Cleaning History — Did It Help?
            </h2>
          </div>
          <p className="text-xs mb-4" style={{ color: "var(--card-sub)" }}>
            Compares your PR for 7 days before and 7 days after each cleaning. A positive change = cleaning helped.
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs border-b" style={{ color: "var(--card-label)", borderColor: "var(--bg-border)" }}>
                  <th className="text-left py-2 pr-4">Date cleaned</th>
                  <th className="text-left py-2 pr-4">Your note</th>
                  <th className="text-right py-2 pr-4">PR before</th>
                  <th className="text-right py-2 pr-4">PR after</th>
                  <th className="text-right py-2">Change</th>
                </tr>
              </thead>
              <tbody>
                {cleaning.map((ev: any, i: number) => {
                  const before = ev.efficiency_before_pct;
                  const after  = ev.efficiency_after_pct;
                  const delta  = (before != null && after != null) ? (after - before) : null;
                  return (
                    <tr key={i} className="border-b last:border-0" style={{ borderColor: "var(--bg-border)" }}>
                      <td className="py-3 pr-4 font-mono text-xs" style={{ color: "var(--card-value)" }}>{ev.date}</td>
                      <td className="py-3 pr-4 text-xs" style={{ color: "var(--text-secondary)" }}>{ev.notes || "—"}</td>
                      <td className="py-3 pr-4 text-right" style={{ color: "var(--card-value)" }}>
                        {before != null ? `${before}%` : <span style={{ color: "var(--card-sub)" }}>—</span>}
                      </td>
                      <td className="py-3 pr-4 text-right" style={{ color: "var(--card-value)" }}>
                        {after != null ? `${after}%` : <span style={{ color: "var(--card-sub)" }}>collecting…</span>}
                      </td>
                      <td className="py-3 text-right font-semibold">
                        {delta != null ? (
                          <span className={`flex items-center justify-end gap-1 ${delta >= 0 ? "text-emerald-500" : "text-red-400"}`}>
                            {delta >= 0 ? <TrendingUp className="w-3.5 h-3.5" /> : <TrendingDown className="w-3.5 h-3.5" />}
                            {delta >= 0 ? "+" : ""}{delta.toFixed(1)}%
                          </span>
                        ) : (
                          <span style={{ color: "var(--card-sub)" }} className="text-xs">need 7 more days</span>
                        )}
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <p className="text-xs mt-3" style={{ color: "var(--card-sub)" }}>
            Log your next cleaning on the <a href="/maintenance" className="text-emerald-500 underline">Maintenance page</a>.
          </p>
        </div>
      )}

      {/* Hour-of-day profile */}
      <div className="themed-card p-6">
        <h2 className="text-lg font-semibold mb-1" style={{ color: "var(--card-title)" }}>
          Hour-of-Day Profile
        </h2>
        <p className="text-xs mb-4" style={{ color: "var(--card-sub)" }}>
          Average expected vs actual at each hour. A consistent gap at a specific hour = shading or soiling at that sun angle.
        </p>
        <div className="h-[240px]">
          <Chart options={hourOptions} series={hourSeries} type="bar" height="100%" />
        </div>
      </div>

    </div>
  );
}
