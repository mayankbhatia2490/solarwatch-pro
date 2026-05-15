"use client";

import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { useTheme } from "next-themes";
import { Activity, Zap } from "lucide-react";

const Chart = dynamic(() => import("react-apexcharts"), { ssr: false });

export default function GridPage() {
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === "dark";
  const [data, setData] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchData() {
      try {
        const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL ?? ""}/api/grid/history?hours=24`);
        if (res.ok) {
          const json = await res.json();
          setData(json.data || []);
        }
      } catch (e) {
        console.error("Failed to fetch grid data", e);
      } finally {
        setLoading(false);
      }
    }
    fetchData();
  }, []);

  if (loading) return <div className="flex items-center justify-center h-64"><div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-emerald-400" /></div>;

  const current = data.length > 0 ? data[data.length - 1] : { voltage_r: 0, frequency: 0 };

  const vOk = current.voltage_r > 207 && current.voltage_r < 253;
  const fOk = current.frequency > 49.5 && current.frequency < 50.5;

  const labelColor = isDark ? "#94a3b8" : "#475569";
  const gridColor  = isDark ? "rgba(148,163,184,0.1)" : "#e2e8f0";

  const combinedSeries = [
    { name: "Voltage (V)",    data: data.map(d => [new Date(d.time).getTime(), +(d.voltage_r  ?? 0).toFixed(1)]) },
    { name: "Frequency (Hz)", data: data.map(d => [new Date(d.time).getTime(), +(d.frequency  ?? 0).toFixed(3)]) },
  ];

  const combinedOptions: any = {
    chart: {
      type: "line",
      toolbar: { show: false },
      zoom: { enabled: false },
      animations: { enabled: false },
      background: "transparent",
    },
    theme: { mode: isDark ? "dark" : "light" },
    colors: ["#ef4444", "#8b5cf6"],
    stroke: { curve: "smooth", width: [2, 2] },
    xaxis: {
      type: "datetime",
      labels: { style: { colors: labelColor }, datetimeUTC: false },
      axisBorder: { show: false },
      axisTicks: { show: false },
    },
    yaxis: [
      {
        seriesName: "Voltage (V)",
        min: 180, max: 280,
        title: { text: "Voltage (V)", style: { color: "#ef4444", fontSize: "11px" } },
        labels: { style: { colors: "#ef4444" }, formatter: (v: number) => `${v.toFixed(0)}V` },
        axisBorder: { show: true, color: "#ef4444" },
      },
      {
        seriesName: "Frequency (Hz)",
        opposite: true,
        min: 48, max: 52,
        title: { text: "Frequency (Hz)", style: { color: "#8b5cf6", fontSize: "11px" } },
        labels: { style: { colors: "#8b5cf6" }, formatter: (v: number) => `${v.toFixed(2)}Hz` },
        axisBorder: { show: true, color: "#8b5cf6" },
      },
    ],
    annotations: {
      yaxis: [
        // Voltage thresholds
        { y: 253, yAxisIndex: 0, borderColor: "#ef4444", strokeDashArray: 4, label: { text: "253V limit", position: "left", style: { color: "#fff", background: "#ef4444", fontSize: "10px" } } },
        { y: 230, yAxisIndex: 0, borderColor: "#22c55e", strokeDashArray: 0, label: { text: "230V nominal", position: "left", style: { color: "#fff", background: "#22c55e", fontSize: "10px" } } },
        { y: 207, yAxisIndex: 0, borderColor: "#ef4444", strokeDashArray: 4, label: { text: "207V limit", position: "left", style: { color: "#fff", background: "#ef4444", fontSize: "10px" } } },
        // Frequency thresholds
        { y: 50.5, yAxisIndex: 1, borderColor: "#a78bfa", strokeDashArray: 4, label: { text: "50.5Hz", position: "right", style: { color: "#fff", background: "#7c3aed", fontSize: "10px" } } },
        { y: 50,   yAxisIndex: 1, borderColor: "#22c55e", strokeDashArray: 0, label: { text: "50Hz nominal", position: "right", style: { color: "#fff", background: "#22c55e", fontSize: "10px" } } },
        { y: 49.5, yAxisIndex: 1, borderColor: "#a78bfa", strokeDashArray: 4, label: { text: "49.5Hz", position: "right", style: { color: "#fff", background: "#7c3aed", fontSize: "10px" } } },
      ],
    },
    grid: { borderColor: gridColor, strokeDashArray: 4 },
    tooltip: {
      theme: isDark ? "dark" : "light",
      shared: true,
      x: { format: "dd MMM HH:mm" },
    },
    legend: {
      show: true,
      position: "top",
      horizontalAlign: "right",
      labels: { colors: isDark ? "#f1f5f9" : "#334155" },
    },
  };

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      <div>
        <h1 className="text-3xl font-bold">Grid Quality</h1>
        <p className="text-[var(--text-secondary)] mt-1">Single-phase voltage and frequency stability · KSY 3.4kW-1Ph</p>
      </div>

      <div className="grid grid-cols-2 gap-4">
        {[
          { label: "Grid Voltage",  value: `${(current.voltage_r  || 0).toFixed(1)}V`,   sub: vOk ? "✓ Normal (207–253V)"       : current.voltage_r  === 0 ? "— No data" : "⚠ Out of range", icon: Zap,      color: vOk ? "text-emerald-400" : "text-amber-400" },
          { label: "Frequency",     value: `${(current.frequency  || 0).toFixed(2)}Hz`,  sub: fOk ? "✓ Normal (49.5–50.5Hz)"    : current.frequency  === 0 ? "— No data" : "⚠ Out of range", icon: Activity, color: fOk ? "text-purple-400"  : "text-amber-400" },
        ].map((c, i) => (
          <div key={i} className="themed-card p-5">
            <div className="flex items-center gap-3 mb-2">
              <div className={`p-2 rounded-lg bg-[var(--bg-hover)] ${c.color}`}>
                <c.icon className="w-4 h-4" />
              </div>
              <div className="text-sm font-medium text-[var(--text-secondary)]">{c.label}</div>
            </div>
            <div className="text-2xl font-bold">{c.value}</div>
            <div className="text-xs mt-1 text-[var(--text-muted)]">{c.sub}</div>
          </div>
        ))}
      </div>

      <div className="themed-card p-6">
        <h2 className="text-lg font-bold mb-1">Voltage & Frequency History (24h)</h2>
        <p className="text-xs mb-4 text-[var(--text-muted)]">
          <span className="text-red-400 font-medium">— Voltage</span> (left axis) &nbsp;·&nbsp;
          <span className="text-purple-400 font-medium">— Frequency</span> (right axis)
        </p>
        <div className="h-[360px]">
          <Chart options={combinedOptions} series={combinedSeries} type="line" height="100%" />
        </div>
      </div>

      {/* Grid voltage note */}
      {!vOk && current.voltage_r > 253 && (
        <div className="themed-card p-4 border-l-4 border-amber-500">
          <p className="text-sm font-semibold text-amber-400">Grid voltage above 253V</p>
          <p className="text-xs mt-1 text-[var(--text-muted)]">
            High voltage ({current.voltage_r.toFixed(1)}V) is common in Haryana during low-load hours. The inverter may
            throttle output to comply with grid standards. Contact UHBVN if voltage consistently exceeds 253V during peak generation hours.
          </p>
        </div>
      )}
    </div>
  );
}
