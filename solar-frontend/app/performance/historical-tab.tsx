"use client";

import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { useTheme } from "next-themes";
import { TrendingDown, CalendarDays, BatteryCharging, Zap, Trophy } from "lucide-react";

const Chart = dynamic(() => import("react-apexcharts"), { ssr: false });

export default function HistoricalTab() {
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === "dark";
  const [data, setData]     = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError]   = useState(false);

  useEffect(() => {
    fetch(`${process.env.NEXT_PUBLIC_API_URL ?? ""}/api/performance`)
      .then(r => r.ok ? r.json() : Promise.reject())
      .then(j => setData(j.data))
      .catch(() => setError(true))
      .finally(() => setLoading(false));
  }, []);

  if (loading) return (
    <div className="flex items-center justify-center h-64">
      <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-emerald-400" />
    </div>
  );
  if (error || !data) return (
    <div className="themed-card p-8 text-center" style={{ color: "var(--text-secondary)" }}>
      Could not load long-term performance data.
    </div>
  );

  const labelColor = isDark ? "#94a3b8" : "#475569";
  const gridColor  = isDark ? "rgba(148,163,184,0.1)" : "#e2e8f0";

  const yoySeries = [
    { name: "This year",   data: data.yoy_data.map((d: any) => d.current_year ?? null) },
    { name: "Last year",   data: data.yoy_data.map((d: any) => d.prev_year    ?? null) },
  ];

  const yoyOptions: any = {
    chart: { type: "bar", background: "transparent", toolbar: { show: false }, animations: { enabled: false } },
    theme: { mode: isDark ? "dark" : "light" },
    colors: ["#22c55e", "#64748b"],
    plotOptions: { bar: { borderRadius: 4, columnWidth: "55%", borderRadiusApplication: "end" } },
    dataLabels: { enabled: false },
    xaxis: {
      categories: data.yoy_data.map((d: any) => d.month),
      labels: { style: { colors: labelColor } },
      axisBorder: { show: false }, axisTicks: { show: false },
    },
    yaxis: {
      labels: { style: { colors: labelColor }, formatter: (v: number) => v != null ? `${v.toFixed(0)}` : "" },
      title: { text: "kWh", style: { color: labelColor } },
    },
    grid: { borderColor: gridColor, strokeDashArray: 4 },
    tooltip: { theme: isDark ? "dark" : "light", y: { formatter: (v: number) => v != null ? `${v.toFixed(1)} kWh` : "No data" } },
    legend: { labels: { colors: isDark ? "#f1f5f9" : "#334155" }, position: "top", horizontalAlign: "right" },
  };

  // Null-safe helpers
  const actualDeg  = data.actual_degradation_pct  != null ? `${data.actual_degradation_pct}%`  : "—";
  const baselinePr = data.baseline_pr              != null ? `${data.baseline_pr}%`              : "—";

  return (
    <div className="space-y-6">

      {/* KPI cards */}
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-4">
        <div className="themed-card p-5">
          <div className="flex items-center gap-2 mb-3">
            <div className="p-2 rounded-lg bg-blue-500/10 border border-blue-500/20">
              <CalendarDays className="w-4 h-4 text-blue-400" />
            </div>
            <span className="text-sm font-medium" style={{ color: "var(--card-label)" }}>System Age</span>
          </div>
          <div className="text-3xl font-black" style={{ color: "var(--card-value)" }}>
            {data.system_age_years}
            <span className="text-sm font-normal ml-1" style={{ color: "var(--text-muted)" }}>yrs</span>
          </div>
          <div className="text-xs mt-1" style={{ color: "var(--card-sub)" }}>{data.system_age_days} days since install</div>
        </div>

        <div className="themed-card p-5">
          <div className="flex items-center gap-2 mb-3">
            <div className="p-2 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
              <BatteryCharging className="w-4 h-4 text-emerald-400" />
            </div>
            <span className="text-sm font-medium" style={{ color: "var(--card-label)" }}>30-day PR</span>
          </div>
          <div className="text-3xl font-black number-gradient">{data.performance_ratio}%</div>
          <div className="text-xs mt-1" style={{ color: "var(--card-sub)" }}>
            Baseline when new: {baselinePr}
          </div>
        </div>

        <div className="themed-card p-5 border-t-2 border-t-amber-500">
          <div className="flex items-center gap-2 mb-3">
            <div className="p-2 rounded-lg bg-amber-500/10 border border-amber-500/20">
              <TrendingDown className="w-4 h-4 text-amber-400" />
            </div>
            <span className="text-sm font-medium" style={{ color: "var(--card-label)" }}>Expected Degradation</span>
          </div>
          <div className="text-3xl font-black text-amber-500">−{data.expected_degradation_pct}%</div>
          <div className="text-xs mt-1" style={{ color: "var(--card-sub)" }}>Vikram Solar warranty curve</div>
        </div>

        <div className="themed-card p-5 border-t-2 border-t-emerald-500">
          <div className="flex items-center gap-2 mb-3">
            <div className="p-2 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
              <Zap className="w-4 h-4 text-emerald-400" />
            </div>
            <span className="text-sm font-medium" style={{ color: "var(--card-label)" }}>Actual Degradation</span>
          </div>
          <div className="text-3xl font-black text-emerald-500">
            {data.actual_degradation_pct != null ? `−${actualDeg}` : "—"}
          </div>
          <div className="text-xs mt-1" style={{ color: "var(--card-sub)" }}>
            {data.actual_degradation_pct == null
              ? "Need ≥ 2 months of data"
              : data.actual_degradation_pct <= data.expected_degradation_pct
                ? "Within warranty range ✓"
                : "Above expected — check panels"}
          </div>
        </div>
      </div>

      {/* YoY chart */}
      <div className="themed-card p-6">
        <h2 className="text-lg font-semibold mb-1" style={{ color: "var(--card-title)" }}>
          Monthly Generation — Year over Year
        </h2>
        <p className="text-xs mb-4" style={{ color: "var(--card-sub)" }}>
          🟢 This year vs ⬛ last year · Grey bars = no data yet for that month
        </p>
        <div className="h-[320px]">
          <Chart options={yoyOptions} series={yoySeries} type="bar" height="100%" />
        </div>
      </div>

      {/* Best days */}
      {data.best_days?.length > 0 && (
        <div className="themed-card p-6">
          <div className="flex items-center gap-2 mb-4">
            <Trophy className="w-5 h-5 text-amber-400" />
            <h2 className="text-lg font-semibold" style={{ color: "var(--card-title)" }}>Best Generation Days</h2>
          </div>
          <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
            {data.best_days.slice(0, 10).map((d: any, i: number) => (
              <div key={i} className="rounded-xl p-3 text-center" style={{ background: "var(--bg-hover)", border: "1px solid var(--bg-border)" }}>
                <div className="text-xs mb-1" style={{ color: "var(--text-muted)" }}>#{i + 1}</div>
                <div className="text-lg font-bold text-emerald-500">{d.kwh}</div>
                <div className="text-xs" style={{ color: "var(--card-sub)" }}>kWh</div>
                <div className="text-xs font-mono mt-1" style={{ color: "var(--text-secondary)" }}>{d.date}</div>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Specs */}
      <div className="themed-card p-5">
        <h2 className="text-base font-semibold mb-3" style={{ color: "var(--card-title)" }}>System Specifications</h2>
        <div className="grid grid-cols-2 md:grid-cols-3 gap-3 text-sm">
          {[
            ["Inverter", data.inverter_model ?? "KSY 3.4kW-1Ph"],
            ["Max Efficiency", `${data.inverter_max_efficiency_pct ?? 98}%`],
            ["Design PR", `${data.design_pr ?? 78}%`],
            ["Total Generated", data.total_energy_kwh ? `${(data.total_energy_kwh / 1000).toFixed(2)} MWh` : "—"],
            ["Panels", "6 × Vikram HyperSol 595W"],
            ["DC Capacity", "3,570 W"],
          ].map(([label, value]) => (
            <div key={label} className="flex justify-between py-2 border-b" style={{ borderColor: "var(--bg-border)" }}>
              <span style={{ color: "var(--card-label)" }}>{label}</span>
              <span className="font-medium" style={{ color: "var(--card-value)" }}>{value}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
