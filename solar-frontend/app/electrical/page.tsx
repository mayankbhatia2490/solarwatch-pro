"use client";
import { useEffect, useState, useCallback } from "react";
import { Zap, Thermometer, Activity, RefreshCw, Wifi } from "lucide-react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "";

interface ElectricalData {
  pv1_voltage: number; pv1_current: number; pv1_power: number;
  pv2_voltage: number; pv2_current: number; pv2_power: number;
  grid_voltage: number; grid_frequency: number; ac_power: number;
  inverter_temp: number; efficiency: number;
}

function MetricRow({ label, value, unit, status }: { label: string; value: string; unit: string; status?: "normal" | "warning" | "unknown" }) {
  const color = status === "normal" ? "text-emerald-400" : status === "warning" ? "text-yellow-400" : "text-slate-400";
  return (
    <div className="flex items-center justify-between py-3 border-b border-slate-800 last:border-0">
      <span className="text-slate-400 text-sm">{label}</span>
      <div className="flex items-center gap-2">
        <span className="text-white font-semibold">{value}<span className="text-slate-400 text-xs ml-1">{unit}</span></span>
        {status && (
          <span className={`text-xs px-2 py-0.5 rounded-full border ${status === "normal" ? "border-emerald-500/30 bg-emerald-500/10 text-emerald-400" : status === "warning" ? "border-yellow-500/30 bg-yellow-500/10 text-yellow-400" : "border-slate-600 bg-slate-800 text-slate-400"}`}>
            {status === "normal" ? "✓ Normal" : status === "warning" ? "⚠ Warning" : "~ Unknown"}
          </span>
        )}
      </div>
    </div>
  );
}

export default function ElectricalPage() {
  const [data, setData] = useState<ElectricalData | null>(null);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState("");

  const load = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/electrical/live`);
      if (res.ok) { setData(await res.json()); setLastUpdated(new Date().toLocaleTimeString()); }
    } catch { /* silently fail */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); const t = setInterval(load, 30000); return () => clearInterval(t); }, [load]);

  if (loading) return (
    <div className="flex items-center justify-center h-64">
      <div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-emerald-400" />
    </div>
  );

  const d = data || {} as ElectricalData;
  const gridOk = (v: number, lo: number, hi: number) => v > lo && v < hi ? "normal" : v === 0 ? "unknown" : "warning";

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Electrical Panel</h1>
          <p className="text-slate-400 text-sm mt-1">Live inverter readings · Updated {lastUpdated || "—"}</p>
        </div>
        <button onClick={load} className="flex items-center gap-2 px-4 py-2 rounded-xl bg-slate-800 text-slate-300 hover:text-white hover:bg-slate-700 transition-all">
          <RefreshCw className="w-4 h-4" /> Refresh
        </button>
      </div>

      {/* DC Input - PV Strings */}
      <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-6">
        <div className="flex items-center gap-2 mb-4">
          <div className="w-8 h-8 rounded-lg bg-amber-500/10 flex items-center justify-center">
            <Zap className="w-4 h-4 text-amber-400" />
          </div>
          <h2 className="font-semibold text-white">DC Input — PV String</h2>
          <span className="ml-auto text-xs text-slate-500">KSY 3.4kW-1Ph · Single MPPT</span>
        </div>
        <div className="bg-slate-800/50 rounded-xl p-4">
          <p className="text-amber-400 text-xs font-medium uppercase tracking-wider mb-3">String 1 · 6× Vikram HyperSol 595W</p>
          <MetricRow label="Voltage" value={d.pv1_voltage?.toFixed(1) ?? "—"} unit="V" status={gridOk(d.pv1_voltage, 100, 450)} />
          <MetricRow label="Current" value={d.pv1_current?.toFixed(2) ?? "—"} unit="A" status={d.pv1_current > 0 ? "normal" : "unknown"} />
          <MetricRow label="Power" value={d.pv1_power?.toFixed(0) ?? "—"} unit="W" status={d.pv1_power > 0 ? "normal" : "unknown"} />
        </div>
      </div>

      {/* AC Output */}
      <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-6">
        <div className="flex items-center gap-2 mb-4">
          <div className="w-8 h-8 rounded-lg bg-blue-500/10 flex items-center justify-center">
            <Wifi className="w-4 h-4 text-blue-400" />
          </div>
          <h2 className="font-semibold text-white">AC Output — Grid</h2>
        </div>
        <MetricRow label="Grid Voltage" value={d.grid_voltage?.toFixed(1) ?? "—"} unit="V" status={gridOk(d.grid_voltage, 210, 250)} />
        <MetricRow label="Grid Frequency" value={d.grid_frequency?.toFixed(1) ?? "—"} unit="Hz" status={gridOk(d.grid_frequency, 49.5, 50.5)} />
        <MetricRow label="AC Output Power" value={d.ac_power?.toFixed(0) ?? "—"} unit="W" status={d.ac_power > 0 ? "normal" : "unknown"} />
      </div>

      {/* Inverter Status */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-6">
          <div className="flex items-center gap-2 mb-4">
            <div className="w-8 h-8 rounded-lg bg-red-500/10 flex items-center justify-center">
              <Thermometer className="w-4 h-4 text-red-400" />
            </div>
            <h2 className="font-semibold text-white">Inverter Temp</h2>
          </div>
          <p className="text-4xl font-bold text-white">{d.inverter_temp?.toFixed(1) ?? "—"}<span className="text-slate-400 text-xl ml-1">°C</span></p>
          <p className={`text-sm mt-2 ${d.inverter_temp > 70 ? "text-red-400" : d.inverter_temp > 55 ? "text-yellow-400" : "text-emerald-400"}`}>
            {d.inverter_temp > 70 ? "⚠ High — check ventilation" : d.inverter_temp > 55 ? "~ Warm — monitor closely" : "✓ Normal operating range"}
          </p>
        </div>
        <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-6">
          <div className="flex items-center gap-2 mb-4">
            <div className="w-8 h-8 rounded-lg bg-purple-500/10 flex items-center justify-center">
              <Activity className="w-4 h-4 text-purple-400" />
            </div>
            <h2 className="font-semibold text-white">Conversion Efficiency</h2>
          </div>
          <p className="text-4xl font-bold text-white">{d.efficiency ? d.efficiency.toFixed(1) : "—"}<span className="text-slate-400 text-xl ml-1">%</span></p>
          <div className="mt-3 h-2 bg-slate-800 rounded-full overflow-hidden">
            <div className="h-full bg-gradient-to-r from-purple-500 to-emerald-400 rounded-full transition-all duration-500" style={{ width: `${Math.min(d.efficiency ?? 0, 100)}%` }} />
          </div>
          <p className="text-slate-400 text-xs mt-2">DC → AC conversion ratio</p>
        </div>
      </div>
    </div>
  );
}
