"use client";
import { useEffect, useState, useCallback } from "react";
import { GitCompare, TrendingUp, TrendingDown, Minus } from "lucide-react";

const API = process.env.NEXT_PUBLIC_API_URL ?? "";

interface StringData {
  pv1_voltage: number; pv1_current: number; pv1_power: number;
  pv2_voltage: number; pv2_current: number; pv2_power: number;
}

function Bar({ value, max, color }: { value: number; max: number; color: string }) {
  const pct = max > 0 ? Math.min((value / max) * 100, 100) : 0;
  return (
    <div className="h-3 bg-slate-800 rounded-full overflow-hidden">
      <div className={`h-full rounded-full transition-all duration-700 ${color}`} style={{ width: `${pct}%` }} />
    </div>
  );
}

function CompareRow({ label, v1, v2, unit }: { label: string; v1: number; v2: number; unit: string }) {
  const diff = v1 - v2;
  const pctDiff = v2 > 0 ? ((diff / v2) * 100).toFixed(1) : "—";
  const maxV = Math.max(v1, v2, 0.01);
  const Icon = diff > 0.5 ? TrendingUp : diff < -0.5 ? TrendingDown : Minus;
  const iconColor = diff > 0.5 ? "text-emerald-400" : diff < -0.5 ? "text-red-400" : "text-slate-400";

  return (
    <div className="py-4 border-b border-slate-800 last:border-0">
      <div className="flex items-center justify-between mb-2">
        <span className="text-slate-400 text-sm">{label}</span>
        <div className="flex items-center gap-1">
          <Icon className={`w-3.5 h-3.5 ${iconColor}`} />
          <span className={`text-xs ${iconColor}`}>{diff > 0.5 || diff < -0.5 ? `${Math.abs(Number(pctDiff))}%` : "Even"}</span>
        </div>
      </div>
      <div className="grid grid-cols-2 gap-4">
        <div>
          <div className="flex justify-between text-xs mb-1">
            <span className="text-amber-400 font-medium">String 1</span>
            <span className="text-white">{v1.toFixed(v1 < 10 ? 2 : 1)} {unit}</span>
          </div>
          <Bar value={v1} max={maxV} color="bg-gradient-to-r from-amber-500 to-amber-400" />
        </div>
        <div>
          <div className="flex justify-between text-xs mb-1">
            <span className="text-blue-400 font-medium">String 2</span>
            <span className="text-white">{v2.toFixed(v2 < 10 ? 2 : 1)} {unit}</span>
          </div>
          <Bar value={v2} max={maxV} color="bg-gradient-to-r from-blue-500 to-blue-400" />
        </div>
      </div>
    </div>
  );
}

export default function StringComparePage() {
  const [data, setData] = useState<StringData | null>(null);
  const [loading, setLoading] = useState(true);
  const [ts, setTs] = useState("");

  const load = useCallback(async () => {
    try {
      const res = await fetch(`${API}/api/electrical/live`);
      if (res.ok) { setData(await res.json()); setTs(new Date().toLocaleTimeString()); }
    } catch { /* ignore */ }
    finally { setLoading(false); }
  }, []);

  useEffect(() => { load(); const t = setInterval(load, 30000); return () => clearInterval(t); }, [load]);

  if (loading) return <div className="flex items-center justify-center h-64"><div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-emerald-400" /></div>;

  const raw = data as Record<string, any> | null;

  // Handle both flat keys (new API) and nested structure (old API), default to 0
  const pv1_power   = Number(raw?.pv1_power   ?? raw?.pv?.string1?.power   ?? 0);
  const pv2_power   = Number(raw?.pv2_power   ?? raw?.pv?.string2?.power   ?? 0);
  const pv1_voltage = Number(raw?.pv1_voltage  ?? raw?.pv?.string1?.voltage ?? 0);
  const pv2_voltage = Number(raw?.pv2_voltage  ?? raw?.pv?.string2?.voltage ?? 0);
  const pv1_current = Number(raw?.pv1_current  ?? raw?.pv?.string1?.current ?? 0);
  const pv2_current = Number(raw?.pv2_current  ?? raw?.pv?.string2?.current ?? 0);

  const d = { pv1_voltage, pv1_current, pv1_power, pv2_voltage, pv2_current, pv2_power };

  const totalPower = pv1_power + pv2_power;
  const s1Pct = totalPower > 0 ? ((pv1_power / totalPower) * 100).toFixed(1) : "—";
  const s2Pct = totalPower > 0 ? ((pv2_power / totalPower) * 100).toFixed(1) : "—";

  return (
    <div className="space-y-6 max-w-3xl mx-auto">
      <div>
        <h1 className="text-2xl font-bold text-white">String Comparison</h1>
        <p className="text-slate-400 text-sm mt-1">PV String 1 vs String 2 · Live · {ts || "—"}</p>
      </div>

      {/* Power split summary */}
      <div className="grid grid-cols-3 gap-4">
        {[
          { label: "String 1 Power", value: `${d.pv1_power.toFixed(0)}W`, sub: `${s1Pct}% of total`, color: "text-amber-400", bg: "bg-amber-500/10" },
          { label: "Combined Output", value: `${totalPower.toFixed(0)}W`, sub: "Total DC input", color: "text-emerald-400", bg: "bg-emerald-500/10" },
          { label: "String 2 Power", value: `${d.pv2_power.toFixed(0)}W`, sub: `${s2Pct}% of total`, color: "text-blue-400", bg: "bg-blue-500/10" },
        ].map((c) => (
          <div key={c.label} className={`${c.bg} border border-slate-800 rounded-2xl p-4 text-center`}>
            <p className="text-slate-400 text-xs mb-1">{c.label}</p>
            <p className={`text-2xl font-bold ${c.color}`}>{c.value}</p>
            <p className="text-slate-500 text-xs mt-1">{c.sub}</p>
          </div>
        ))}
      </div>

      {/* Bar comparison */}
      <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-6">
        <div className="flex items-center gap-2 mb-5">
          <div className="w-8 h-8 rounded-lg bg-purple-500/10 flex items-center justify-center">
            <GitCompare className="w-4 h-4 text-purple-400" />
          </div>
          <h2 className="font-semibold text-white">Live Comparison</h2>
          <div className="ml-auto flex items-center gap-4 text-xs">
            <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded bg-amber-400" /> String 1</span>
            <span className="flex items-center gap-1.5"><span className="w-3 h-3 rounded bg-blue-400" /> String 2</span>
          </div>
        </div>
        <CompareRow label="Voltage" v1={d.pv1_voltage} v2={d.pv2_voltage} unit="V" />
        <CompareRow label="Current" v1={d.pv1_current} v2={d.pv2_current} unit="A" />
        <CompareRow label="Power" v1={d.pv1_power} v2={d.pv2_power} unit="W" />
      </div>

      {/* Health insight */}
      <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-6">
        <h2 className="font-semibold text-white mb-3">Health Insight</h2>
        {d.pv2_voltage === 0 ? (
          <div className="flex items-start gap-3 p-3 bg-slate-800 rounded-xl">
            <span className="text-2xl">ℹ️</span>
            <div>
              <p className="text-white text-sm font-medium">String 2 not detected</p>
              <p className="text-slate-400 text-xs mt-1">Your inverter may be single-string or String 2 panels are shaded/offline. This is normal for single-MPPT inverters.</p>
            </div>
          </div>
        ) : Math.abs(d.pv1_power - d.pv2_power) / Math.max(d.pv1_power, d.pv2_power, 1) > 0.2 ? (
          <div className="flex items-start gap-3 p-3 bg-yellow-500/10 border border-yellow-500/20 rounded-xl">
            <span className="text-2xl">⚠️</span>
            <div>
              <p className="text-yellow-400 text-sm font-medium">Power imbalance detected</p>
              <p className="text-slate-400 text-xs mt-1">Strings differ by more than 20%. Check for shading, dirty panels, or loose connections on the weaker string.</p>
            </div>
          </div>
        ) : (
          <div className="flex items-start gap-3 p-3 bg-emerald-500/10 border border-emerald-500/20 rounded-xl">
            <span className="text-2xl">✅</span>
            <div>
              <p className="text-emerald-400 text-sm font-medium">Strings balanced</p>
              <p className="text-slate-400 text-xs mt-1">Both strings are performing within 20% of each other. No action needed.</p>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
