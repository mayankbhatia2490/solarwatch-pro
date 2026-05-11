"use client";
import { useEffect, useState, useCallback, useRef } from "react";
import { Sun, Zap, IndianRupee, Leaf, Activity, Thermometer, Wind, Cloud, RefreshCw, TrendingUp, AlertCircle, CheckCircle, AlertTriangle, Calendar } from "lucide-react";
import { GenerationChart } from "@/components/generation-chart";
import { fetchDashboardSummary, fetchDailyChart, fetchHealthScorecard } from "@/lib/api";

// ── Helpers ────────────────────────────────────────────────────────────────────

function isNighttime(sunriseISO?: string, sunsetISO?: string): boolean {
  const now = Date.now();
  if (!sunriseISO || !sunsetISO) {
    // Fallback: Karnal approx 6:00–19:30 IST
    const h = new Date().getHours();
    return h < 6 || h >= 19;
  }
  return now < new Date(sunriseISO).getTime() || now > new Date(sunsetISO).getTime();
}

// ── Time range config ──────────────────────────────────────────────────────────

const QUICK_RANGES = [
  { label: "1h",   value: "1h"  },
  { label: "4h",   value: "4h"  },
  { label: "8h",   value: "8h"  },
  { label: "12h",  value: "12h" },
  { label: "1 Day",value: "today"},
  { label: "Yesterday", value: "yesterday" },
  { label: "7 Days",value: "7d" },
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
    <div className={`glass-card rounded-2xl p-5 border ${c.border} ${c.bg} flex flex-col gap-3`}>
      <div className="flex items-center justify-between">
        <span className="text-sm font-medium" style={{ color: "var(--card-label)" }}>{label}</span>
        <div className={`w-8 h-8 rounded-xl ${c.bg} border ${c.border} flex items-center justify-center`}>
          <Icon className={`w-4 h-4 ${c.icon}`} />
        </div>
      </div>
      <div className={`text-3xl font-bold ${c.gradient}`}>{value}</div>
      {sub && <div className="text-xs" style={{ color: "var(--card-sub)" }}>{sub}</div>}
    </div>
  );
}

function HeroCard({ power, capacity_pct, status, night }: any) {
  const isGenerating = power > 0 && status === "online";
  const isNight = night && status === "offline";
  const pct = Math.min(capacity_pct, 100);

  const statusLabel = isGenerating
    ? "Generating"
    : isNight
    ? "Night / Standby"
    : "Offline";

  const statusNote = isGenerating
    ? `Generating at ${pct.toFixed(0)}% of 3.5kW capacity`
    : isNight
    ? "System is resting — no solar generation at night (normal)"
    : "System offline — check inverter";

  return (
    <div className={`glass-card rounded-2xl p-6 border ${isGenerating ? "border-emerald-500/25" : "border-slate-700/50"} relative overflow-hidden`}>
      {isGenerating && (
        <div className="absolute inset-0 bg-gradient-to-br from-emerald-500/5 via-transparent to-transparent pointer-events-none" />
      )}
      <div className="flex items-start justify-between mb-6">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <span className={`w-2 h-2 rounded-full ${isGenerating ? "pulse-green bg-emerald-400" : isNight ? "bg-indigo-400" : "bg-slate-500"}`} />
            <span className={`text-xs font-medium ${isGenerating ? "text-emerald-400" : isNight ? "text-indigo-400" : "text-slate-500"}`}>
              {statusLabel}
            </span>
          </div>
          <div className="text-sm font-medium" style={{ color: "var(--card-label)" }}>Current Output</div>
        </div>
        <Sun className={`w-6 h-6 ${isGenerating ? "text-emerald-400" : isNight ? "text-indigo-300" : "text-slate-500"}`} />
      </div>

      <div className="flex items-end gap-6 mb-6">
        <div>
          <div className={`text-6xl font-black tracking-tight ${isGenerating ? "number-gradient" : "text-slate-500"}`}>
            {power >= 1000 ? `${(power / 1000).toFixed(2)}` : `${power.toFixed(0)}`}
          </div>
          <div className="text-slate-400 text-lg font-medium mt-1">{power >= 1000 ? "kW" : "W"}</div>
        </div>
        {/* Circular gauge */}
        <div className="relative w-24 h-24">
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

      <div className="text-xs" style={{ color: "var(--card-sub)" }}>{statusNote}</div>
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

// ── Chart range + date picker bar ─────────────────────────────────────────────

function ChartRangeBar({ range, setRange, from, to, setFrom, setTo }: any) {
  const [showPicker, setShowPicker] = useState(false);

  function applyCustom() {
    if (from && to) {
      setRange("custom");
      setShowPicker(false);
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-2">
      {/* Quick range pills */}
      <div className="chart-range-bar">
        {QUICK_RANGES.map(r => (
          <button
            key={r.value}
            onClick={() => { setRange(r.value); setShowPicker(false); }}
            className={`chart-range-btn ${range === r.value && range !== "custom" ? "active" : ""}`}
          >
            {r.label}
          </button>
        ))}
      </div>

      {/* Custom date range button */}
      <button
        onClick={() => setShowPicker(!showPicker)}
        className={`flex items-center gap-1.5 chart-range-btn border ${showPicker || range === "custom" ? "active border-emerald-500/40" : ""}`}
        style={{ borderColor: "var(--bg-border)", borderRadius: "0.6rem" }}
      >
        <Calendar className="w-3 h-3" />
        {range === "custom" && from && to
          ? `${from} → ${to}`
          : "Date Range"}
      </button>

      {/* Date picker dropdown */}
      {showPicker && (
        <div className="absolute mt-1 z-30 glass-card rounded-xl p-4 shadow-xl border flex gap-3 items-end flex-wrap"
             style={{ top: "100%", right: 0, borderColor: "var(--bg-border)", minWidth: 280 }}>
          <div>
            <label className="text-xs mb-1 block" style={{ color: "var(--card-label)" }}>From</label>
            <input type="date" value={from} onChange={e => setFrom(e.target.value)}
              className="text-xs px-2 py-1.5 rounded-lg border outline-none"
              style={{ background: "var(--bg-surface-2)", borderColor: "var(--bg-border)", color: "var(--card-value)" }}
            />
          </div>
          <div>
            <label className="text-xs mb-1 block" style={{ color: "var(--card-label)" }}>To</label>
            <input type="date" value={to} onChange={e => setTo(e.target.value)}
              className="text-xs px-2 py-1.5 rounded-lg border outline-none"
              style={{ background: "var(--bg-surface-2)", borderColor: "var(--bg-border)", color: "var(--card-value)" }}
            />
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

// ── Main page ──────────────────────────────────────────────────────────────────

export default function Dashboard() {
  const [summary, setSummary] = useState<any>(null);
  const [chart, setChart] = useState<any>(null);
  const [scorecard, setScorecard] = useState<any>(null);
  const [chartRange, setChartRange] = useState("today");
  const [customFrom, setCustomFrom] = useState("");
  const [customTo, setCustomTo] = useState("");
  const [loading, setLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date());
  const [refreshing, setRefreshing] = useState(false);

  // Live power ticks every 30s independently from the full load
  const [livePower, setLivePower] = useState<number | null>(null);
  const liveTimerRef = useRef<ReturnType<typeof setInterval> | undefined>(undefined);

  const loadLivePower = useCallback(async () => {
    try {
      const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8090";
      const res = await fetch(`${API_BASE}/api/dashboard/summary`, { cache: "no-store" });
      if (res.ok) {
        const d = await res.json();
        setLivePower(d.power_now_w ?? 0);
      }
    } catch {}
  }, []);

  const load = useCallback(async () => {
    setRefreshing(true);
    try {
      const fromParam = chartRange === "custom" ? customFrom : undefined;
      const toParam   = chartRange === "custom" ? customTo   : undefined;
      const [s, c, sc] = await Promise.all([
        fetchDashboardSummary(),
        fetchDailyChart(chartRange, fromParam, toParam),
        fetchHealthScorecard(),
      ]);
      setSummary(s);
      setLivePower(s.power_now_w ?? 0);
      setChart(c);
      setScorecard(sc);
      setLastRefresh(new Date());
    } catch (e) {
      console.error(e);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, [chartRange, customFrom, customTo]);

  // Full reload on range change
  useEffect(() => { load(); }, [load]);

  // Full reload every 5 min
  useEffect(() => {
    const t = setInterval(load, 300000);
    return () => clearInterval(t);
  }, [load]);

  // Live power tick every 30 s
  useEffect(() => {
    liveTimerRef.current = setInterval(loadLivePower, 30000);
    return () => clearInterval(liveTimerRef.current);
  }, [loadLivePower]);

  const power = livePower ?? summary?.power_now_w ?? 0;
  const health = summary?.health_score ?? 0;
  const healthColor = health >= 80 ? "text-emerald-500" : health >= 60 ? "text-amber-500" : "text-red-500";

  // Sunset-aware: determine if offline is because of night
  const night = isNighttime(summary?.sunrise, summary?.sunset);

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
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold" style={{ color: "var(--card-value)" }}>Dashboard</h1>
          <p className="text-sm mt-0.5" style={{ color: "var(--card-sub)" }}>
            Last updated {lastRefresh.toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="px-3 py-1.5 rounded-xl glass-card flex items-center gap-2">
            <span className="text-xs" style={{ color: "var(--card-label)" }}>Health</span>
            <span className={`text-sm font-bold ${healthColor}`}>{health}/100</span>
          </div>
          <button onClick={load} disabled={refreshing}
            className="p-2 rounded-xl glass-card text-slate-400 hover:text-slate-200 transition-colors">
            <RefreshCw className={`w-4 h-4 ${refreshing ? "animate-spin" : ""}`} />
          </button>
        </div>
      </div>

      {/* Hero + Stats grid */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div className="lg:col-span-2">
          <HeroCard power={power} capacity_pct={summary?.capacity_pct ?? 0} status={summary?.status ?? "offline"} night={night} />
        </div>
        <div className="space-y-4">
          <StatCard label="Today's Generation" value={`${(summary?.energy_today_kwh ?? 0).toFixed(1)} kWh`} sub="Total energy produced today" icon={Zap} color="blue" />
          <StatCard label="Today's Savings" value={`₹${(summary?.savings_today_inr ?? 0).toFixed(0)}`} sub="At ₹6.5/kWh tariff" icon={IndianRupee} color="amber" />
        </div>
      </div>

      {/* Savings summary */}
      <div className="grid grid-cols-3 gap-4">
        <StatCard label="This Month" value={`₹${(summary?.savings_month_inr ?? 0).toLocaleString("en-IN")}`} icon={IndianRupee} color="amber" />
        <StatCard label="CO₂ Saved" value={`${(summary?.co2_total_kg ?? 0).toFixed(0)} kg`} sub={`${summary?.trees_equivalent ?? 0} trees equivalent`} icon={Leaf} color="emerald" />
        <StatCard label="Total Generated" value={`${((summary?.total_energy_kwh ?? 0) / 1000).toFixed(1)} MWh`} sub="Since installation" icon={TrendingUp} color="purple" />
      </div>

      {/* Generation chart with extended time range controls */}
      <div className="glass-card rounded-2xl p-5">
        <div className="flex flex-wrap items-center justify-between gap-3 mb-4 relative">
          <h2 className="font-semibold" style={{ color: "var(--card-title)" }}>Generation Chart</h2>
          <ChartRangeBar
            range={chartRange} setRange={setChartRange}
            from={customFrom} to={customTo}
            setFrom={setCustomFrom} setTo={setCustomTo}
          />
        </div>
        <GenerationChart data={chart?.data ?? []} />
      </div>

      {/* Health Scorecard */}
      <div className="glass-card rounded-2xl p-5">
        <h2 className="font-semibold mb-4" style={{ color: "var(--card-title)" }}>System Health Scorecard</h2>
        <div className="space-y-0">
          {(scorecard?.rows ?? []).map((row: any, i: number) => (
            <HealthRow key={i} {...row} />
          ))}
        </div>
      </div>

      {/* Environmental + Payback */}
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <div className="glass-card rounded-2xl p-5 border border-emerald-500/15">
          <div className="flex items-center gap-2 mb-4">
            <Leaf className="w-4 h-4 text-emerald-500" />
            <h2 className="font-semibold" style={{ color: "var(--card-title)" }}>Environmental Impact</h2>
          </div>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <div className="text-2xl font-bold number-gradient">{(summary?.co2_today_kg ?? 0).toFixed(1)} kg</div>
              <div className="text-xs mt-1" style={{ color: "var(--card-sub)" }}>CO₂ offset today</div>
            </div>
            <div>
              <div className="text-2xl font-bold number-gradient">{(summary?.co2_total_kg ?? 0).toFixed(0)} kg</div>
              <div className="text-xs mt-1" style={{ color: "var(--card-sub)" }}>CO₂ offset total</div>
            </div>
          </div>
          <div className="mt-4 text-xs italic" style={{ color: "var(--card-sub)" }}>
            Equivalent to planting {summary?.trees_equivalent ?? 0} trees 🌳
          </div>
        </div>

        <div className="glass-card rounded-2xl p-5">
          <div className="flex items-center gap-2 mb-4">
            <TrendingUp className="w-4 h-4 text-blue-500" />
            <h2 className="font-semibold" style={{ color: "var(--card-title)" }}>Investment Payback</h2>
          </div>
          <PaybackBar
            recovered={summary?.savings_total_inr ?? 0}
            total={summary?.system_cost_inr ?? 220000}
            pct={summary?.payback_pct ?? 0}
          />
          {summary?.years_to_payback > 0 && (
            <div className="mt-3 text-xs" style={{ color: "var(--card-sub)" }}>
              Estimated full payback in ~{summary.years_to_payback.toFixed(1)} years at current rate
            </div>
          )}
        </div>
      </div>

      {/* Current Conditions */}
      <div className="glass-card rounded-2xl p-5">
        <h2 className="font-semibold mb-4" style={{ color: "var(--card-title)" }}>Current Conditions</h2>
        <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
          {[
            { label: "W/m² irradiance", value: `${summary?.solar_radiation_wm2?.toFixed(0) ?? "—"}`, icon: Sun, iconClass: "text-amber-500", bg: "bg-amber-500/10 border-amber-500/20" },
            { label: "cloud cover",     value: `${summary?.cloud_cover_pct?.toFixed(0) ?? "—"}%`, icon: Cloud, iconClass: "text-blue-500", bg: "bg-blue-500/10 border-blue-500/20" },
            { label: "inverter temp",   value: `${summary?.inverter_temp_c?.toFixed(0) ?? "—"}°C`, icon: Thermometer, iconClass: "text-red-500", bg: "bg-red-500/10 border-red-500/20" },
            { label: "health score",    value: `${summary?.health_score ?? "—"}/100`, icon: Activity, iconClass: "text-emerald-500", bg: "bg-emerald-500/10 border-emerald-500/20" },
          ].map(({ label, value, icon: Icon, iconClass, bg }) => (
            <div key={label} className="flex items-center gap-3">
              <div className={`w-9 h-9 rounded-xl ${bg} border flex items-center justify-center`}>
                <Icon className={`w-4 h-4 ${iconClass}`} />
              </div>
              <div>
                <div className="text-lg font-bold" style={{ color: "var(--card-value)" }}>{value}</div>
                <div className="text-xs" style={{ color: "var(--card-sub)" }}>{label}</div>
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
