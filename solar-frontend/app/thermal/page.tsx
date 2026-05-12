"use client";

import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { useTheme } from "next-themes";
import { Thermometer, Zap, AlertTriangle } from "lucide-react";

const Chart = dynamic(() => import("react-apexcharts"), { ssr: false });

export default function ThermalPage() {
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === "dark";
  const [data, setData] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchData() {
      try {
        const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL ?? ""}/api/thermal/history?hours=24`);
        if (res.ok) {
          const json = await res.json();
          setData(json.data || []);
        }
      } catch (e) {
        console.error("Failed to fetch thermal data", e);
      } finally {
        setLoading(false);
      }
    }
    fetchData();
  }, []);

  if (loading) return <div className="flex items-center justify-center h-64"><div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-emerald-400" /></div>;

  const current = data.length > 0 ? data[data.length - 1] : { radiator_temp: 0, module_temp: 0, power_w: 0 };
  
  const series = [
    { name: "Radiator Temp", type: "line", data: data.map(d => [new Date(d.time).getTime(), d.radiator_temp]) },
    { name: "Module Temp", type: "line", data: data.map(d => [new Date(d.time).getTime(), d.module_temp]) },
    { name: "Output Power", type: "area", data: data.map(d => [new Date(d.time).getTime(), d.power_w]) },
  ];

  const options: any = {
    chart: { type: "line", toolbar: { show: false }, zoom: { enabled: false }, animations: { enabled: false } },
    theme: { mode: isDark ? "dark" : "light" },
    stroke: { curve: "smooth", width: [3, 3, 0] },
    colors: ["#ef4444", "#f97316", "#22c55e"], // Red, Orange, Green
    fill: {
      type: ['solid', 'solid', 'gradient'],
      gradient: { shadeIntensity: 1, opacityFrom: 0.4, opacityTo: 0.05, stops: [0, 90, 100] }
    },
    xaxis: { type: "datetime", labels: { style: { colors: isDark ? "#94a3b8" : "#475569" } }, axisBorder: { show: false }, axisTicks: { show: false } },
    yaxis: [
      { 
        title: { text: "Temperature (°C)", style: { color: "#ef4444" } }, 
        labels: { style: { colors: isDark ? "#94a3b8" : "#475569" }, formatter: (v: number) => `${v.toFixed(1)}°C` },
        min: 20, max: 80
      },
      { 
        show: false, // share the same axis for module temp
        min: 20, max: 80
      },
      { 
        opposite: true, 
        title: { text: "Power (W)", style: { color: "#22c55e" } },
        labels: { style: { colors: isDark ? "#94a3b8" : "#475569" }, formatter: (v: number) => `${v.toFixed(0)}W` },
        min: 0, max: 4000
      }
    ],
    grid: { borderColor: isDark ? "rgba(148, 163, 184, 0.1)" : "#e2e8f0", strokeDashArray: 4 },
    tooltip: { theme: isDark ? "dark" : "light", shared: true, intersect: false },
    legend: { labels: { colors: isDark ? "#f1f5f9" : "#334155" } },
    annotations: {
      yAxis: [
        { y: 65, borderColor: '#eab308', strokeDashArray: 4, label: { text: 'Warn (65°C)', style: { color: '#000', background: '#eab308' } } },
        { y: 75, borderColor: '#ef4444', strokeDashArray: 4, label: { text: 'Derating (75°C)', style: { color: '#fff', background: '#ef4444' } } }
      ]
    }
  };

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Thermal Diagnostics</h1>
          <p className="text-[var(--text-secondary)] mt-1">Dual-sensor temperature tracking vs output power</p>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {[
          { label: "Radiator Temp", value: `${current.radiator_temp.toFixed(1)}°C`, icon: Thermometer, color: current.radiator_temp > 65 ? "text-red-400" : "text-emerald-400" },
          { label: "Module Temp", value: `${current.module_temp.toFixed(1)}°C`, icon: Thermometer, color: current.module_temp > 70 ? "text-red-400" : "text-emerald-400" },
          { label: "Live Output", value: `${current.power_w.toFixed(0)}W`, icon: Zap, color: "text-emerald-400" },
        ].map((c, i) => (
          <div key={i} className="themed-card p-5">
            <div className="flex items-center gap-3 mb-2">
              <div className={`p-2 rounded-lg bg-[var(--bg-hover)] ${c.color}`}>
                <c.icon className="w-5 h-5" />
              </div>
              <div className="text-sm font-medium text-[var(--text-secondary)]">{c.label}</div>
            </div>
            <div className="text-2xl font-bold">{c.value}</div>
          </div>
        ))}
      </div>

      <div className="themed-card p-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-bold">Temperature vs Output (24h)</h2>
          {current.radiator_temp >= 75 && (
            <div className="flex items-center gap-2 text-red-500 bg-red-500/10 px-3 py-1.5 rounded-lg text-sm font-medium">
              <AlertTriangle className="w-4 h-4" />
              Active Derating
            </div>
          )}
        </div>
        <div className="h-[400px]">
          <Chart options={options} series={series} type="line" height="100%" />
        </div>
      </div>
    </div>
  );
}
