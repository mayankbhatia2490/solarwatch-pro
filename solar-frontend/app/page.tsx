"use client";
import { useEffect, useState, useCallback, useRef } from "react";
import dynamic from "next/dynamic";
import { useTheme } from "next-themes";
import { Sun, Zap, IndianRupee, Leaf, Activity, Cloud, CloudSun, CloudDrizzle, RefreshCw, TrendingUp, AlertCircle, CheckCircle, AlertTriangle, Calendar, Droplets } from "lucide-react";
import { GenerationChart } from "@/components/generation-chart";
import { ActionCards } from "@/components/action-cards";
import { fetchDashboardSummary, fetchDailyChart, fetchHealthScorecard } from "@/lib/api";

const Chart = dynamic(() => import("react-apexcharts"), { ssr: false });

// ── Helpers ────────────────────────────────────────────────────────────────────

function isNighttime(sunriseISO?: string, sunsetISO?: string): boolean {
  const now = Date.now();
  if (!sunriseISO || !sunsetISO) {
    const h = new Date().getHours();
    return h < 6 || h >= 19;
  }
  return now < new Date(sunriseISO).getTime() || now > new Date(sunsetISO).getTime();
}

const QUICK_RANGES = [
  { label: "1h",        value: "1h"       },
  { label: "4h",        value: "4h"       },
  { label: "8h",        value: "8h"       },
  { label: "12h",       value: "12h"      },
  { label: "1 Day",     value: "today"    },
  { label: "Yesterday", value: "yesterday"},
  { label: "7 Days",    value: "7d"       },
];

// ── Sub-components ─────────────────────────────────────────────────────────────

function StatCard({ label, value, sub, icon: Icon, color = "emerald" }: any) {
  const colors: any = {
    emerald: { bg: "bg-emerald-500/10", border: "border-emerald-500/20", icon: "text-emerald-500", gradient: "number-gradient" },
    blue:    { bg: "bg-blue-500/10",    border: "border-blue-500/20",    icon: "text-blue-500",    gradient: "number-gradient-blue" },
    amber:   { bg: "bg-amber-500/10",   border: "border-amber-500/20",   icon: "text-amber-500",   gradient: "number-gradient-amber" },
    purple:  { bg: "bg-purple-500/10",  border: "border-purple-500/20",  icon: "text-purple-500",  gradient: "number-gradient-blue" },
  };
  const c = colors[color];
  return (
    <div className={`glass-card rounded-2xl p-4 border ${c.border} ${c.bg} flex flex-col gap-2`}>
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium" style={{ color: "var(--card-label)" }}>{label}</span>
        <div className={`w-7 h-7 rounded-lg ${c.bg} border ${c.border} flex items-center justify-center`}>
          <Icon className={`w-3.5 h-3.5 ${c.icon}`} />
        </div>
      </div>
      <div className={`text-2xl font-bold ${c.gradient}`}>{value}</div>
      {sub && <div className="text-xs" style={{ color: "var(--card-sub)" }}>{sub}</div>}
    </div>
  );
}

function HeroCard({ power, capacity_pct, status, night }: any) {
  const isGenerating = power > 0 && status === "online";
  const isNight = night && status === "offline";
  const pct = Math.min(capacity_pct, 100);
  const statusLabel = isGenerating ? "Generating" : isNight ? "Night / Standby" : "Offline";
  const statusNote  = isGenerating
    ? `Generating at ${pct.toFixed(0)}% of 3.5kW capacity`
    : isNight
    ? "System is resting — no solar generation at night (normal)"
    : "System offline — check inverter";

  return (
    <div className={`glass-card rounded-2xl p-5 border ${isGenerating ? "border-emerald-500/25" : "border-slate-700/50"} relative overflow-hidden`}>
      {isGenerating && (
        <div className="absolute inset-0 bg-gradient-to-br from-emerald-500/5 via-transparent to-transparent pointer-events-none" />
      )}
      <div className="flex items-start justify-between mb-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className={`w-2 h-2 rounded-full ${isGenerating ? "pulse-green bg-emerald-400" : isNight ? "bg-indigo-400" : "bg-slate-500"}`} />
            <span className={`text-xs font-medium ${isGenerating ? "text-emerald-400" : isNight ? "text-indigo-400" : "text-slate-500"}`}>
              {statusLabel}
            </span>
          </div>
          <div className="text-sm font-medium" style={{ color: "var(--card-label)" }}>Current Output</div>
        </div>
        <Sun className={`w-5 h-5 ${isGenerating ? "text-emerald-400" : isNight ? "text-indigo-300" : "text-slate-500"}`} />
      </div>

      <div className="flex items-end gap-5 mb-4">
        <div>
          <div className={`text-5xl font-black tracking-tight ${isGenerating ? "number-gradient" : "text-slate-500"}`}>
            {power >= 1000 ? `${(power / 1000).toFixed(2)}` : `${power.toFixed(0)}`}
          </div>
          <div className="text-slate-400 text-base font-medium mt-1">{power >= 1000 ? "kW" : "W"}</div>
        </div>
        <div className="relative w-20 h-20">
          <svg viewBox="0 0 80 80" className="w-full h-full -rotate-90">
            <circle cx="40" cy="40" r="32" fill="none" stroke="#1e293b" strokeWidth="8" />
            <circle
              cx="40" cy="40" r="32" fill="none"
              stroke={isGenerating ? "#22c55e" : "#374151"}
              strokeWidth="8" strokeLinecap="round"
              strokeDasharray={`${2 * Math.PI * 32}`}
              strokeDashoffset={`${2 * Math.PI * 32 * (1 - pct / 100)}`}
              className="transition-all duration-1000"
            />
          </svg>
          <div className="absolute inset-0 flex flex-col items-center justify-center">
            <span className="text-lg font-bold" style={{ color: "var(--card-value)" }}>{pct.toFixed(0)}%</span>
            <span className="text-xs text-slate-500">of cap.</span>
          </div>
        </div>
      </div>
      <div className="text-xs mt-2" style={{ color: "var(--card-sub)" }}>{statusNote}</div>
    </div>
  );
}

function HealthRow({ parameter, value, status }: any) {
  const icons: any = {
    normal:   <CheckCircle className="w-3.5 h-3.5 text-emerald-500" />,
    warning:  <AlertTriangle className="w-3.5 h-3.5 text-amber-500" />,
    critical: <AlertCircle className="w-3.5 h-3.5 text-red-500" />,
    unknown:  <Activity className="w-3.5 h-3.5 text-slate-400" />,
  };
  return (
    <div className="flex items-center justify-between py-2.5 border-b last:border-0" style={{ borderColor: "var(--bg-border)" }}>
      <span className="text-sm" style={{ color: "var(--card-label)" }}>{parameter}</span>
      <div className="flex items-center gap-2">
        <span className="text-sm font-medium" style={{ color: "var(--card-value)" }}>{value}</span>
        <span className={`px-2 py-0.5 rounded-full text-xs font-medium status-${status} flex items-center gap-1`}>
          {icons[status]}
          {status.charAt(0).toUpperCase() + status.slice(1)}
        </span>
      </div>
    </div>
  );
}

function PaybackBar({ recovered, total, pct }: any) {
  const milestones = [25, 50, 75];
  return (
    <div>
      <div className="flex justify-between text-sm mb-3">
        <span className="font-medium" style={{ color: "var(--card-value)" }}>₹{recovered.toLocaleString("en-IN")} recovered</span>
        <span style={{ color: "var(--card-sub)" }}>of ₹{total.toLocaleString("en-IN")}</span>
      </div>
      <div className="relative h-3 rounded-full overflow-hidden" style={{ background: "var(--bg-surface-2)" }}>
        <div
          className="h-full bg-gradient-to-r from-emerald-500 to-green-400 rounded-full transition-all duration-1000"
          style={{ width: `${pct}%` }}
        />
        {milestones.map(m => (
          <div key={m} className="absolute top-0 bottom-0 w-px" style={{ left: `${m}%`, background: "var(--bg-border)" }} />
        ))}
      </div>
      <div className="flex justify-between mt-1.5 text-xs" style={{ color: "var(--card-sub)" }}>
        {milestones.map(m => <span key={m}>{m}%</span>)}
        <span>100%</span>
      </div>
      <div className="mt-2 text-xs" style={{ color: "var(--card-sub)" }}>{pct.toFixed(1)}% complete</div>
    </div>
  );
}

function ChartRangeBar({ range, setRange, from, to, setFrom, setTo }: any) {
  const [showPicker, setShowPicker] = useState(false);
  function applyCustom() {
    if (from && to) { setRange("custom"); setShowPicker(false); }
  }
  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="chart-range-bar">
        {QUICK_RANGES.map(r => (
          <button key={r.value} onClick={() => { setRange(r.value); setShowPicker(false); }}
            className={`chart-range-btn ${range === r.value && range !== "custom" ? "active" : ""}`}>
            {r.label}
          </button>
        ))}
      </div>
      <button onClick={() => setShowPicker(!showPicker)}
        className={`flex items-center gap-1.5 chart-range-btn border ${showPicker || range === "custom" ? "active border-emerald-500/40" : ""}`}
        style={{ borderColor: "var(--bg-border)", borderRadius: "0.6rem" }}>
        <Calendar className="w-3 h-3" />
        {range === "custom" && from && to ? `${from} → ${to}` : "Date Range"}
      </button>
      {showPicker && (
        <div className="absolute mt-1 z-30 glass-card rounded-xl p-4 shadow-xl border flex gap-3 items-end flex-wrap"
             style={{ top: "100%", right: 0, borderColor: "var(--bg-border)", minWidth: 280 }}>
          <div>
            <label className="text-xs mb-1 block" style={{ color: "var(--card-label)" }}>From</label>
            <input type="date" value={from} onChange={e => setFrom(e.target.value)}
              className="text-xs px-2 py-1.5 rounded-lg border outline-none"
              style={{ background: "var(--bg-surface-2)", borderColor: "var(--bg-border)", color: "var(--card-value)" }} />
          </div>
          <div>
            <label className="text-xs mb-1 block" style={{ color: "var(--card-label)" }}>To</label>
            <input type="date" value={to} onChange={e => setTo(e.target.value)}
              className="text-xs px-2 py-1.5 rounded-lg border outline-none"
              style={{ background: "var(--bg-surface-2)", borderColor: "var(--bg-border)", color: "var(--card-value)" }} />
          </div>
          <button onClick={applyCustom}
            className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-emerald-500 text-white hover:bg-emerald-600 transition-colors">
            Apply
          </button>
        </div>
      )}
    </div>
  );
}

// ── Weather pill (header) ─────────────────────────────────────────────────────

function WeatherPill({ wx }: { wx: any }) {
  if (!wx?.data?.current) return null;

  const cur   = wx.data.current;
  const cloud = cur.cloud_cover ?? 0;
  const temp  = cur.temperature_2m ?? null;
  const irr   = wx.data.solar_radiation_wm2 ?? cur.shortwave_radiation ?? null;
  const expW  = wx.data.expected_power_w ?? null;

  const SkyIcon  = cloud < 15 ? Sun : cloud < 40 ? CloudSun : cloud < 70 ? Cloud : CloudDrizzle;
  const skyColor = cloud < 15 ? "text-amber-400" : cloud < 40 ? "text-amber-300" : cloud < 70 ? "text-slate-400" : "text-blue-400";

  const items = [
    { Icon: SkyIcon,     value: temp  != null ? `${temp.toFixed(0)}°C` : "—",                                    color: skyColor,         label: "outdoor" },
    { Icon: Cloud,       value: `${cloud}%`,                                                                       color: "text-blue-400",  label: "cloud"   },
    { Icon: Zap,         value: irr   != null ? `${irr.toFixed(0)} W/m²` : "—",                                  color: "text-amber-400", label: "irr"     },
    { Icon: TrendingUp,  value: expW  != null ? (expW >= 1000 ? `${(expW/1000).toFixed(1)} kW` : `${expW.toFixed(0)} W`) : "—", color: "text-emerald-400", label: "exp" },
  ];

  return (
    <div className="hidden sm:flex items-center gap-0 rounded-2xl overflow-hidden border transition-all duration-200"
      style={{ background: "var(--bg-surface-2)", borderColor: "var(--bg-border)" }}>
      {items.map(({ Icon, value, color, label }, i) => (
        <div key={label} className="flex items-center gap-1.5 px-3 py-2">
          {i > 0 && <div className="w-px h-3.5 mr-3" style={{ background: "var(--bg-border)" }} />}
          <Icon className={`w-3.5 h-3.5 flex-shrink-0 ${color}`} />
          <span className="text-xs font-medium" style={{ color: "var(--card-value)" }}>{value}</span>
        </div>
      ))}
    </div>
  );
}

// ── Performance section ────────────────────────────────────────────────────────

function PerformanceSection({ analysis, cleaning, isDark }: { analysis: any; cleaning: any; isDark: boolean }) {
  if (!analysis) return null;

  const s = analysis.summary;
  const labelColor = isDark ? "#94a3b8" : "#475569";
  const gridColor  = isDark ? "rgba(148,163,184,0.1)" : "#e2e8f0";

  const prColor = s.overall_pr_pct >= 78 ? "text-emerald-500" : s.overall_pr_pct >= 65 ? "text-amber-500" : "text-red-500";
  const lostKwh = Math.max(s.total_expected_kwh - s.total_actual_kwh, 0);

  // Mini 7-day bar chart
  const barSeries = [
    { name: "Expected", data: analysis.daily_bars.map((d: any) => d.expected_kwh) },
    { name: "Actual",   data: analysis.daily_bars.map((d: any) => d.actual_kwh)   },
  ];
  const barOptions: any = {
    chart: { type: "bar", background: "transparent", toolbar: { show: false }, animations: { enabled: false }, sparkline: { enabled: false } },
    theme: { mode: isDark ? "dark" : "light" },
    colors: ["#3b82f6", "#22c55e"],
    plotOptions: { bar: { columnWidth: "70%", borderRadius: 3, borderRadiusApplication: "end" } },
    dataLabels: { enabled: false },
    xaxis: {
      categories: analysis.daily_bars.map((d: any) => d.date.slice(5)),
      labels: { style: { colors: labelColor, fontSize: "10px" }, rotate: -45 },
      axisBorder: { show: false }, axisTicks: { show: false },
    },
    yaxis: { labels: { style: { colors: labelColor, fontSize: "10px" }, formatter: (v: number) => `${v.toFixed(0)}` } },
    grid: { borderColor: gridColor, strokeDashArray: 4 },
    tooltip: { theme: isDark ? "dark" : "light", y: { formatter: (v: number) => `${v.toFixed(1)} kWh` } },
    legend: { labels: { colors: isDark ? "#f1f5f9" : "#334155", fontSize: "11px" }, position: "top", horizontalAlign: "right" },
  };

  const urgencyBorder = cleaning?.urgency === "high" ? "border-l-red-500" : cleaning?.urgency === "medium" ? "border-l-amber-500" : "border-l-emerald-500";
  const urgencyIcon   = cleaning?.urgency === "high" ? "text-red-500" : cleaning?.urgency === "medium" ? "text-amber-500" : "text-emerald-500";

  return (
    <div className="space-y-4">
      {/* Section header */}
      <div className="flex items-center justify-between">
        <h2 className="font-semibold" style={{ color: "var(--card-title)" }}>7-day Performance</h2>
        <a href="/performance" className="text-xs text-emerald-500 hover:underline">Full analysis →</a>
      </div>

      {/* KPI strip */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        {[
          { label: "Performance Ratio", value: `${s.overall_pr_pct}%`, sub: `${s.overall_pr_pct >= 78 ? "✓ Above" : "↓ Below"} 78% baseline`, valueClass: prColor },
          { label: "Weather-expected",  value: `${s.total_expected_kwh} kWh`, sub: "Based on real irradiance", valueClass: "number-gradient-blue" },
          { label: "Actually generated", value: `${s.total_actual_kwh} kWh`, sub: "Inverter measured",        valueClass: "number-gradient" },
          { label: "Generation gap",    value: lostKwh > 0.5 ? `${lostKwh.toFixed(1)} kWh` : "None ✓", sub: lostKwh > 0.5 ? `≈ ₹${s.lost_inr} unrealised` : "All generation accounted for", valueClass: lostKwh > 0.5 ? "text-amber-500" : "text-emerald-500" },
        ].map(({ label, value, sub, valueClass }) => (
          <div key={label} className="glass-card rounded-2xl p-4">
            <div className="text-xs mb-2" style={{ color: "var(--card-label)" }}>{label}</div>
            <div className={`text-2xl font-bold ${valueClass}`}>{value}</div>
            <div className="text-xs mt-1" style={{ color: "var(--card-sub)" }}>{sub}</div>
          </div>
        ))}
      </div>

      {/* Mini chart + clean status side by side on large screens */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2 glass-card rounded-2xl p-5">
          <p className="text-xs mb-3" style={{ color: "var(--card-sub)" }}>
            🔵 Expected (weather-adjusted) · 🟢 Actual inverter output
          </p>
          {analysis.daily_bars.length === 0 ? (
            <div className="h-32 flex items-center justify-center text-sm" style={{ color: "var(--card-sub)" }}>
              No data yet — appears after first sunny day
            </div>
          ) : (
            <div className="h-[180px]">
              <Chart options={barOptions} series={barSeries} type="bar" height="100%" />
            </div>
          )}
        </div>

        <div className="space-y-3">
          {/* Clean status */}
          {cleaning && (
            <div className={`glass-card rounded-2xl p-4 border-l-4 ${urgencyBorder}`}>
              <div className="flex items-start gap-3">
                <Droplets className={`w-4 h-4 mt-0.5 flex-shrink-0 ${urgencyIcon}`} />
                <div>
                  <div className="text-sm font-semibold" style={{ color: "var(--card-value)" }}>
                    {cleaning.urgency === "high" ? "Clean panels now" : cleaning.urgency === "medium" ? "Cleaning soon" : "Panels clean ✓"}
                  </div>
                  <div className="text-xs mt-0.5" style={{ color: "var(--text-secondary)" }}>
                    {cleaning.days_since_cleaning} days since last clean
                    {cleaning.current_efficiency_pct != null && ` · ${cleaning.current_efficiency_pct}% efficiency`}
                  </div>
                  <a href="/maintenance" className="text-xs text-emerald-500 hover:underline mt-1 inline-block">Log cleaning →</a>
                </div>
              </div>
            </div>
          )}

          {/* Top recommendation */}
          {analysis.recommendations?.slice(0, 1).map((r: any, i: number) => (
            <div key={i} className="glass-card rounded-2xl p-4">
              <div className="text-xs font-semibold mb-1" style={{ color: "var(--card-value)" }}>
                {r.icon} {r.title}
              </div>
              <div className="text-xs" style={{ color: "var(--text-secondary)" }}>{r.detail}</div>
              <div className="mt-2 text-xs font-medium text-emerald-500">→ {r.action}</div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────────

export default function Dashboard() {
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === "dark";

  const [summary, setSummary]     = useState<any>(null);
  const [chart, setChart]         = useState<any>(null);
  const [scorecard, setScorecard] = useState<any>(null);
  const [analysis, setAnalysis]   = useState<any>(null);
  const [cleaning, setCleaning]   = useState<any>(null);
  const [weather, setWeather]     = useState<any>(null);
  const [chartRange, setChartRange] = useState("today");
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo]     = useState("");
  const [loading, setLoading]       = useState(true);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());
  const [refreshing, setRefreshing]   = useState(false);
  const [livePower, setLivePower]     = useState<number | null>(null);
  const liveTimerRef = useRef<ReturnType<typeof setInterval> | undefined>(undefined);

  const loadLivePower = useCallback(async () => {
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL ?? ""}/api/dashboard/summary`, { cache: "no-store" });
      if (res.ok) { const d = await res.json(); setLivePower(d.power_now_w ?? 0); }
    } catch {}
  }, []);

  const load = useCallback(async () => {
    setRefreshing(true);
    try {
      const API = process.env.NEXT_PUBLIC_API_URL ?? "";
      const fromParam = chartRange === "custom" ? customFrom : undefined;
      const toParam   = chartRange === "custom" ? customTo   : undefined;
      const [s, c, sc, an, cl, wx] = await Promise.all([
        fetchDashboardSummary(),
        fetchDailyChart(chartRange, fromParam, toParam),
        fetchHealthScorecard(),
        fetch(`${API}/api/analysis?days=7`).then(r => r.ok ? r.json() : null).catch(() => null),
        fetch(`${API}/api/cleaning`).then(r => r.ok ? r.json() : null).catch(() => null),
        fetch(`${API}/api/weather`).then(r => r.ok ? r.json() : null).catch(() => null),
      ]);
      setSummary(s);
      setLivePower(s.power_now_w ?? 0);
      setChart(c);
      setScorecard(sc);
      setAnalysis(an);
      setCleaning(cl);
      setWeather(wx);
      setLastRefresh(new Date());
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [chartRange, customFrom, customTo]);

  useEffect(() => { load(); }, [load]);
  useEffect(() => { const t = setInterval(load, 300000); return () => clearInterval(t); }, [load]);
  useEffect(() => {
    liveTimerRef.current = setInterval(loadLivePower, 30000);
    return () => clearInterval(liveTimerRef.current);
  }, [loadLivePower]);

  const power       = livePower ?? summary?.power_now_w ?? 0;
  const health      = summary?.health_score ?? 0;
  const healthColor = health >= 80 ? "text-emerald-500" : health >= 60 ? "text-amber-500" : "text-red-500";
  const night       = isNighttime(summary?.sunrise, summary?.sunset);

  if (loading) {
    return (
      <div className="pt-16 lg:pt-0 space-y-4">
        <div className="skeleton h-8 w-48 mb-6" />
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {[...Array(3)].map((_, i) => <div key={i} className="skeleton h-40 rounded-2xl" />)}
        </div>
        <div className="skeleton h-80 rounded-2xl" />
      </div>
    );
  }

  return (
    <div className="pt-16 lg:pt-0 space-y-5 max-w-7xl">
      {/* Header */}
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold" style={{ color: "var(--card-value)" }}>Dashboard</h1>
          <p className="text-sm mt-0.5" style={{ color: "var(--card-sub)" }}>
            Last updated {lastRefresh.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}
          </p>
        </div>
        <div className="flex items-center gap-3 flex-wrap">
          {/* Weather pill — all params, SVG icons, glassmorphism */}
          <WeatherPill wx={weather} />
          {/* Health badge */}
          <div className="px-3 py-2 rounded-2xl glass-card border flex items-center gap-2 transition-all duration-200"
            style={{ borderColor: "var(--bg-border)" }}>
            <Activity className={`w-3.5 h-3.5 ${healthColor}`} />
            <span className="text-xs" style={{ color: "var(--card-label)" }}>Health</span>
            <span className={`text-sm font-bold ${healthColor}`}>{health}/100</span>
          </div>
          <button onClick={load} disabled={refreshing} title="Refresh"
            className="p-2 rounded-xl glass-card border text-slate-400 hover:text-slate-200 transition-all duration-200 cursor-pointer disabled:cursor-not-allowed"
            style={{ borderColor: "var(--bg-border)" }}>
            <RefreshCw className={`w-4 h-4 ${refreshing ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>

      {/* Hero + Stats grid */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
        <div className="lg:col-span-2">
          <HeroCard power={power} capacity_pct={summary?.capacity_pct ?? 0} status={summary?.status ?? "offline"} night={night} />
        </div>
        <div className="lg:col-span-3 grid grid-cols-2 lg:grid-cols-3 gap-4">
          <StatCard label="Today's Generation" value={`${(summary?.energy_today_kwh ?? 0).toFixed(1)} kWh`} icon={Zap} color="blue" />
          <StatCard label="Today's Savings" value={`₹${(summary?.savings_today_inr ?? 0).toFixed(0)}`} sub="Electricity offset today" icon={IndianRupee} color="amber" />
          <StatCard label="This Month" value={`₹${(summary?.savings_month_inr ?? 0).toLocaleString("en-IN")}`} sub="Month-to-date savings" icon={IndianRupee} color="amber" />
          <StatCard label="Total Generated" value={`${((summary?.total_energy_kwh ?? 0) / 1000).toFixed(2)} MWh`} sub="Since installation" icon={TrendingUp} color="purple" />
          <StatCard label="CO₂ Avoided" value={`${(summary?.co2_total_kg ?? 0).toFixed(0)} kg`} sub={`≈ ${summary?.trees_equivalent ?? 0} trees`} icon={Leaf} color="emerald" />
          <StatCard label="Payback" value={`${(summary?.payback_pct ?? 0).toFixed(1)}%`} sub={`₹${(summary?.savings_total_inr ?? 0).toLocaleString("en-IN")} of ₹${(summary?.system_cost_inr ?? 190000).toLocaleString("en-IN")}`} icon={TrendingUp} color="blue" />
        </div>
      </div>

      {/* Generation chart */}
      <div className="glass-card rounded-2xl p-5">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4 relative">
          <h2 className="font-semibold" style={{ color: "var(--card-title)" }}>Generation Chart</h2>
          <ChartRangeBar range={chartRange} setRange={setChartRange} from={customFrom} to={customTo} setFrom={setCustomFrom} setTo={setCustomTo} />
        </div>
        <GenerationChart data={chart?.data ?? []} />
      </div>

      {/* ── 7-day Performance section ─────────────────────────────────────────── */}
      <PerformanceSection analysis={analysis} cleaning={cleaning} isDark={isDark} />

      {/* Health Scorecard */}
      <div className="glass-card rounded-2xl p-5">
        <h2 className="font-semibold mb-4" style={{ color: "var(--card-title)" }}>System Health Scorecard</h2>
        <div className="space-y-0">
          {(scorecard?.rows ?? []).map((row: any, i: number) => (
            <HealthRow key={i} {...row} />
          ))}
        </div>
      </div>

      {/* Action flashcards — only shown when there are quick wins */}
      <ActionCards />

      {/* Environmental + Payback */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="glass-card rounded-2xl p-5 border border-emerald-500/15">
          <div className="flex items-center gap-2 mb-4">
            <Leaf className="w-4 h-4 text-emerald-500" />
            <h2 className="font-semibold" style={{ color: "var(--card-title)" }}>Environmental Impact</h2>
          </div>
          <div className="grid grid-cols-3 gap-4">
            <div>
              <div className="text-2xl font-bold number-gradient">{(summary?.co2_today_kg ?? 0).toFixed(1)} kg</div>
              <div className="text-xs mt-1" style={{ color: "var(--card-sub)" }}>CO₂ today</div>
            </div>
            <div>
              <div className="text-2xl font-bold number-gradient">{(summary?.co2_total_kg ?? 0).toFixed(0)} kg</div>
              <div className="text-xs mt-1" style={{ color: "var(--card-sub)" }}>CO₂ total</div>
            </div>
            <div>
              <div className="text-2xl font-bold number-gradient">{summary?.trees_equivalent ?? 0}</div>
              <div className="text-xs mt-1" style={{ color: "var(--card-sub)" }}>trees equivalent</div>
            </div>
          </div>
        </div>

        <div className="glass-card rounded-2xl p-5">
          <div className="flex items-center gap-2 mb-4">
            <TrendingUp className="w-4 h-4 text-blue-500" />
            <h2 className="font-semibold" style={{ color: "var(--card-title)" }}>Investment Payback</h2>
          </div>
          <PaybackBar
            recovered={summary?.savings_total_inr ?? 0}
            total={summary?.system_cost_inr ?? 190000}
            pct={summary?.payback_pct ?? 0}
          />
          {summary?.years_to_payback > 0 && (
            <div className="mt-3 text-xs" style={{ color: "var(--card-sub)" }}>
              Estimated full payback in ~{summary.years_to_payback.toFixed(1)} years at current rate
            </div>
          )}
        </div>
      </div>

    </div>
  );
}
