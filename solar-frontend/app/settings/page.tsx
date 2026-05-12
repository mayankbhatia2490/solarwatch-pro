"use client";
import { useState, useEffect } from "react";
import { useTheme } from "next-themes";
import { Settings, Zap, IndianRupee, Palette, Save, CheckCircle, Loader2 } from "lucide-react";

function Field({ label, id, type = "text", value, onChange, unit, hint }: {
  label: string; id: string; type?: string; value: string;
  onChange: (v: string) => void; unit?: string; hint?: string;
}) {
  return (
    <div>
      <label htmlFor={id} className="block text-sm text-slate-400 mb-1.5">{label}</label>
      <div className="flex items-center gap-2">
        <input id={id} type={type} value={value} onChange={(e) => onChange(e.target.value)}
          className="flex-1 bg-slate-800 border border-slate-700 rounded-xl px-4 py-2.5 text-white text-sm focus:outline-none focus:border-emerald-500 transition-colors" />
        {unit && <span className="text-slate-400 text-sm w-10 shrink-0">{unit}</span>}
      </div>
      {hint && <p className="text-slate-500 text-xs mt-1">{hint}</p>}
    </div>
  );
}

export default function SettingsPage() {
  const { theme: currentTheme, setTheme } = useTheme();
  const [saved, setSaved] = useState(false);
  const [form, setForm] = useState({
    plantName: "My Solar System Karnal",
    installDate: "2025-04-17",
    capacity: "3500",
    tariff: "6.5",
    systemCost: "220000",
    timezone: "Asia/Kolkata",
    theme: currentTheme || "dark",
    dateFormat: "DD/MM/YYYY",
  });

  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    async function loadSettings() {
      try {
        const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL ?? ""}/api/settings`);
        if (res.ok) {
          const data = await res.json();
          setForm(f => ({
            ...f,
            plantName: data.plant_name || f.plantName,
            installDate: data.installation_date || f.installDate,
            capacity: data.installed_capacity_w?.toString() || f.capacity,
            tariff: data.electricity_tariff_inr?.toString() || f.tariff,
            systemCost: data.system_cost_inr?.toString() || f.systemCost,
            timezone: data.timezone || f.timezone,
          }));
        }
      } catch (err) {
        console.error("Failed to load settings", err);
      } finally {
        setLoading(false);
      }
    }
    loadSettings();
  }, []);

  const set = (key: keyof typeof form) => (v: string) => setForm((f) => ({ ...f, [key]: v }));

  const handleSave = async () => {
    setSaving(true);
    setTheme(form.theme);
    
    try {
      await fetch(`${process.env.NEXT_PUBLIC_API_URL ?? ""}/api/settings`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          plant_name: form.plantName,
          installation_date: form.installDate,
          installed_capacity_w: parseFloat(form.capacity) || 3500,
          electricity_tariff_inr: parseFloat(form.tariff) || 6.5,
          system_cost_inr: parseFloat(form.systemCost) || 220000,
          timezone: form.timezone
        })
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (err) {
      console.error("Failed to save settings", err);
    } finally {
      setSaving(false);
    }
  };


  const systemAge = () => {
    const install = new Date(form.installDate);
    const now = new Date();
    const months = Math.floor((now.getTime() - install.getTime()) / (1000 * 60 * 60 * 24 * 30.44));
    return `${months} months`;
  };

  const estimatedPayback = () => {
    const cost = parseFloat(form.systemCost) || 0;
    const tariff = parseFloat(form.tariff) || 6.5;
    const cap = parseFloat(form.capacity) || 3500;
    const dailyKwh = (cap / 1000) * 4.5; // avg 4.5 sun hours
    const dailySavings = dailyKwh * tariff;
    const years = cost / (dailySavings * 365);
    return years.toFixed(1);
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center min-h-[400px]">
        <Loader2 className="w-8 h-8 animate-spin text-emerald-500" />
      </div>
    );
  }

  return (
    <div className="space-y-6 max-w-2xl mx-auto">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">Settings</h1>
          <p className="text-slate-400 text-sm mt-1">System configuration and preferences</p>
        </div>
        <button onClick={handleSave} disabled={saving}
          className={`flex items-center gap-2 px-5 py-2.5 rounded-xl font-medium text-sm transition-all disabled:opacity-50 ${saved ? "bg-emerald-600 text-white" : "bg-emerald-500 hover:bg-emerald-400 text-white"}`}>
          {saving ? <><Loader2 className="w-4 h-4 animate-spin" /> Saving...</> : saved ? <><CheckCircle className="w-4 h-4" /> Saved!</> : <><Save className="w-4 h-4" /> Save Changes</>}
        </button>
      </div>

      {/* System Info */}
      <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-6 space-y-4">
        <div className="flex items-center gap-2 mb-2">
          <div className="w-8 h-8 rounded-lg bg-emerald-500/10 flex items-center justify-center">
            <Settings className="w-4 h-4 text-emerald-400" />
          </div>
          <h2 className="font-semibold text-white">System Information</h2>
        </div>
        <Field label="Plant Name" id="plantName" value={form.plantName} onChange={set("plantName")} />
        <Field label="Installation Date" id="installDate" type="date" value={form.installDate} onChange={set("installDate")}
          hint={`System age: ${systemAge()}`} />
        <Field label="Installed Capacity" id="capacity" value={form.capacity} onChange={set("capacity")} unit="W"
          hint="Total peak DC capacity of your panels" />
        <Field label="Timezone" id="timezone" value={form.timezone} onChange={set("timezone")} hint="Used for chart time axes" />

        {/* Read-only system stats */}
        <div className="grid grid-cols-2 gap-3 pt-2">
          {[
            { label: "Inverter", value: "ShineMonitor API" },
            { label: "Collector Interval", value: "Every 5 min" },
            { label: "InfluxDB", value: "solar_metrics" },
            { label: "API Version", value: "v1.0 MVP" },
          ].map((s) => (
            <div key={s.label} className="bg-slate-800/50 rounded-xl p-3">
              <p className="text-slate-500 text-xs">{s.label}</p>
              <p className="text-slate-300 text-sm font-medium mt-0.5">{s.value}</p>
            </div>
          ))}
        </div>
      </div>

      {/* Financial */}
      <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-6 space-y-4">
        <div className="flex items-center gap-2 mb-2">
          <div className="w-8 h-8 rounded-lg bg-amber-500/10 flex items-center justify-center">
            <IndianRupee className="w-4 h-4 text-amber-400" />
          </div>
          <h2 className="font-semibold text-white">Financial Settings</h2>
        </div>
        <Field label="Electricity Tariff" id="tariff" type="number" value={form.tariff} onChange={set("tariff")} unit="₹/kWh"
          hint="Your local grid electricity rate — used to calculate savings" />
        <Field label="System Cost" id="systemCost" type="number" value={form.systemCost} onChange={set("systemCost")} unit="₹"
          hint="Total installation cost — used for payback calculation" />

        {/* Payback preview */}
        <div className="bg-amber-500/5 border border-amber-500/20 rounded-xl p-4">
          <p className="text-amber-400 text-sm font-medium">Estimated payback period</p>
          <p className="text-white text-2xl font-bold mt-1">{estimatedPayback()} years</p>
          <p className="text-slate-400 text-xs mt-1">Based on ₹{form.tariff}/kWh tariff, {(parseFloat(form.capacity)/1000).toFixed(1)}kW system, avg 4.5 sun hours/day</p>
        </div>
      </div>

      {/* Display */}
      <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-6 space-y-4">
        <div className="flex items-center gap-2 mb-2">
          <div className="w-8 h-8 rounded-lg bg-purple-500/10 flex items-center justify-center">
            <Palette className="w-4 h-4 text-purple-400" />
          </div>
          <h2 className="font-semibold text-white">Display Preferences</h2>
        </div>

        <div>
          <p className="text-sm text-slate-400 mb-2">Theme</p>
          <div className="flex gap-3">
            {["dark", "light", "system"].map((t) => (
              <button key={t} onClick={() => set("theme")(t)}
                className={`flex-1 py-2 rounded-xl text-sm font-medium capitalize transition-all border ${form.theme === t ? "border-emerald-500 bg-emerald-500/10 text-emerald-400" : "border-slate-700 text-slate-400 hover:border-slate-600"}`}>
                {t === "dark" ? "🌙 Dark" : t === "light" ? "☀️ Light" : "💻 System"}
              </button>
            ))}
          </div>
        </div>

        <div>
          <p className="text-sm text-slate-400 mb-2">Date Format</p>
          <div className="flex gap-3">
            {["DD/MM/YYYY", "MM/DD/YYYY", "YYYY-MM-DD"].map((f) => (
              <button key={f} onClick={() => set("dateFormat")(f)}
                className={`flex-1 py-2 rounded-xl text-xs font-mono transition-all border ${form.dateFormat === f ? "border-emerald-500 bg-emerald-500/10 text-emerald-400" : "border-slate-700 text-slate-400 hover:border-slate-600"}`}>
                {f}
              </button>
            ))}
          </div>
        </div>
      </div>

      {/* Data */}
      <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-6">
        <div className="flex items-center gap-2 mb-4">
          <div className="w-8 h-8 rounded-lg bg-blue-500/10 flex items-center justify-center">
            <Zap className="w-4 h-4 text-blue-400" />
          </div>
          <h2 className="font-semibold text-white">Data & Export</h2>
        </div>
        <div className="flex flex-col sm:flex-row gap-3">
          <a href={`${process.env.NEXT_PUBLIC_API_URL ?? ""}/api/export/csv`}
            className="flex-1 text-center px-4 py-2.5 rounded-xl border border-slate-700 text-slate-300 hover:text-white hover:border-slate-500 text-sm font-medium transition-all">
            📥 Export All Data (CSV)
          </a>
          <a href={`${process.env.NEXT_PUBLIC_API_URL ?? ""}/docs`} target="_blank" rel="noreferrer"
            className="flex-1 text-center px-4 py-2.5 rounded-xl border border-slate-700 text-slate-300 hover:text-white hover:border-slate-500 text-sm font-medium transition-all">
            📖 API Documentation
          </a>
        </div>
        <p className="text-slate-500 text-xs mt-3 text-center">Data stored in InfluxDB · Collection every 5 min · Retention: unlimited</p>
      </div>
    </div>
  );
}
