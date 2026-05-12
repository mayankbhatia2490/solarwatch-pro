"use client";

import { useEffect, useState } from "react";
import dynamic from "next/dynamic";
import { Activity, Zap } from "lucide-react";

const Chart = dynamic(() => import("react-apexcharts"), { ssr: false });

export default function GridPage() {
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

  const seriesVoltage = [
    { name: "Voltage", data: data.map(d => [new Date(d.time).getTime(), d.voltage_r]) },
  ];

  const seriesFrequency = [
    { name: "Frequency", data: data.map(d => [new Date(d.time).getTime(), d.frequency]) },
  ];

  const commonOptions: any = {
    chart: { type: "line", toolbar: { show: false }, zoom: { enabled: false }, animations: { enabled: false } },
    theme: { mode: "dark" },
    stroke: { curve: "smooth", width: 2 },
    xaxis: { type: "datetime", labels: { style: { colors: "#94a3b8" } }, axisBorder: { show: false }, axisTicks: { show: false } },
    grid: { borderColor: "rgba(148, 163, 184, 0.1)", strokeDashArray: 4 },
    tooltip: { theme: "dark" },
    legend: { show: false }
  };

  const voltageOptions = {
    ...commonOptions,
    colors: ["#ef4444"],
    yaxis: { min: 180, max: 280, labels: { style: { colors: "#94a3b8" }, formatter: (v: number) => `${v.toFixed(0)}V` } },
    annotations: {
      yAxis: [
        { y: 230, borderColor: '#22c55e', label: { text: 'Nominal 230V', style: { color: '#fff', background: '#22c55e' } } },
        { y: 253, borderColor: '#ef4444', strokeDashArray: 2 },
        { y: 207, borderColor: '#ef4444', strokeDashArray: 2 }
      ]
    }
  };

  const frequencyOptions = {
    ...commonOptions,
    colors: ["#8b5cf6"],
    yaxis: { min: 48, max: 52, labels: { style: { colors: "#94a3b8" }, formatter: (v: number) => `${v.toFixed(2)}Hz` } },
    annotations: {
      yAxis: [
        { y: 50, borderColor: '#22c55e', label: { text: 'Nominal 50Hz', style: { color: '#fff', background: '#22c55e' } } },
        { y: 50.5, borderColor: '#ef4444', strokeDashArray: 2 },
        { y: 49.5, borderColor: '#ef4444', strokeDashArray: 2 }
      ]
    }
  };

  const vOk = current.voltage_r > 207 && current.voltage_r < 253;
  const fOk = current.frequency > 49.5 && current.frequency < 50.5;

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Grid Quality</h1>
          <p className="text-[var(--text-secondary)] mt-1">Single-phase voltage and frequency stability · KSY 3.4kW-1Ph</p>
        </div>
      </div>

      <div className="grid grid-cols-2 gap-4">
        {[
          { label: "Grid Voltage", value: `${(current.voltage_r || 0).toFixed(1)}V`, sub: vOk ? "✓ Normal (207–253V)" : current.voltage_r === 0 ? "— No data" : "⚠ Out of range", icon: Zap, color: vOk ? "text-emerald-400" : "text-amber-400" },
          { label: "Frequency", value: `${(current.frequency || 0).toFixed(2)}Hz`, sub: fOk ? "✓ Normal (49.5–50.5Hz)" : current.frequency === 0 ? "— No data" : "⚠ Out of range", icon: Activity, color: fOk ? "text-purple-400" : "text-amber-400" },
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
        <h2 className="text-lg font-bold mb-4">Voltage History (24h)</h2>
        <div className="h-[300px]">
          <Chart options={voltageOptions} series={seriesVoltage} type="line" height="100%" />
        </div>
      </div>

      <div className="themed-card p-6">
        <h2 className="text-lg font-bold mb-4">Frequency History (24h)</h2>
        <div className="h-[250px]">
          <Chart options={frequencyOptions} series={seriesFrequency} type="line" height="100%" />
        </div>
      </div>
    </div>
  );
}
