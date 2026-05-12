"use client";

import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { TrendingDown, CalendarDays, BatteryCharging, Zap } from "lucide-react";

const Chart = dynamic(() => import("react-apexcharts"), { ssr: false });

export default function PerformancePage() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchData() {
      try {
        const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL ?? ""}/api/performance`);
        if (res.ok) {
          const json = await res.json();
          setData(json.data);
        }
      } catch (e) {
        console.error("Failed to fetch performance data", e);
      } finally {
        setLoading(false);
      }
    }
    fetchData();
  }, []);

  if (loading) return <div className="flex items-center justify-center h-64"><div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-emerald-400" /></div>;
  if (!data) return <div>No data available</div>;

  const yoySeries = [
    { name: "Current Year", data: data.yoy_data.map((d: any) => d.current_year) },
    { name: "Previous Year", data: data.yoy_data.map((d: any) => d.prev_year || 0) },
  ];

  const yoyOptions: any = {
    chart: { type: "bar", toolbar: { show: false } },
    theme: { mode: "dark" },
    colors: ["#22c55e", "#64748b"], // Green, Slate
    plotOptions: { bar: { borderRadius: 4, columnWidth: '50%' } },
    dataLabels: { enabled: false },
    xaxis: { categories: data.yoy_data.map((d: any) => d.month), labels: { style: { colors: "#94a3b8" } }, axisBorder: { show: false }, axisTicks: { show: false } },
    yaxis: { title: { text: "Energy (kWh)", style: { color: "#94a3b8" } }, labels: { style: { colors: "#94a3b8" } } },
    grid: { borderColor: "rgba(148, 163, 184, 0.1)", strokeDashArray: 4 },
    tooltip: { theme: "dark" },
    legend: { labels: { colors: "#f1f5f9" } }
  };

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Long-Term Performance</h1>
          <p className="text-[var(--text-secondary)] mt-1">Degradation analysis and YoY comparisons</p>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="themed-card p-5">
          <div className="flex items-center gap-3 mb-2">
            <div className="p-2 rounded-lg bg-[var(--bg-hover)] text-blue-400"><CalendarDays className="w-5 h-5" /></div>
            <div className="text-sm font-medium text-[var(--text-secondary)]">System Age</div>
          </div>
          <div className="text-2xl font-bold">{data.system_age_years} <span className="text-sm font-normal text-[var(--text-muted)]">Years</span></div>
        </div>

        <div className="themed-card p-5">
          <div className="flex items-center gap-3 mb-2">
            <div className="p-2 rounded-lg bg-[var(--bg-hover)] text-emerald-400"><BatteryCharging className="w-5 h-5" /></div>
            <div className="text-sm font-medium text-[var(--text-secondary)]">Performance Ratio</div>
          </div>
          <div className="text-2xl font-bold">{data.performance_ratio}%</div>
        </div>

        <div className="themed-card p-5 border-t-2 border-t-amber-500">
          <div className="flex items-center gap-3 mb-2">
            <div className="p-2 rounded-lg bg-[var(--bg-hover)] text-amber-500"><TrendingDown className="w-5 h-5" /></div>
            <div className="text-sm font-medium text-[var(--text-secondary)]">Expected Degradation</div>
          </div>
          <div className="text-2xl font-bold text-amber-500">-{data.expected_degradation_pct}%</div>
        </div>

        <div className="themed-card p-5 border-t-2 border-t-emerald-500">
          <div className="flex items-center gap-3 mb-2">
            <div className="p-2 rounded-lg bg-[var(--bg-hover)] text-emerald-500"><Zap className="w-5 h-5" /></div>
            <div className="text-sm font-medium text-[var(--text-secondary)]">Actual Degradation</div>
          </div>
          <div className="text-2xl font-bold text-emerald-500">-{data.actual_degradation_pct}%</div>
        </div>
      </div>

      <div className="themed-card p-6">
        <h2 className="text-lg font-bold mb-4">Year Over Year Generation</h2>
        <div className="h-[350px]">
          <Chart options={yoyOptions} series={yoySeries} type="bar" height="100%" />
        </div>
      </div>
    </div>
  );
}
