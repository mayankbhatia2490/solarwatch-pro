"use client";
import { useState, useEffect } from "react";
import { useTheme } from "next-themes";
import { Settings, Zap, IndianRupee, Palette, Save, CheckCircle, Loader2, AlertTriangle, RefreshCw, RotateCcw } from "lucide-react";
import { PageTabs, TabPanel } from "@/components/page-tabs";
import AlertsPage from "@/app/alerts/page";

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

function SystemSettings() {
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
    const dailyKwh = (cap / 1000) * 4.5;
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
    <div className="space-y-6 max-w-2xl">
      <div className="flex items-center justify-end">
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

function CalibrationSettings() {
  const [cal, setCal] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [resetting, setResetting] = useState(false);
  const [msg, setMsg] = useState("");

  const API = process.env.NEXT_PUBLIC_API_URL ?? "";

  async function load() {
    try {
      const res = await fetch(`${API}/api/calibrate/status`);
      if (res.ok) setCal(await res.json());
    } catch {}
    setLoading(false);
  }

  useEffect(() => { load(); }, []);

  // Poll while calibration is running
  useEffect(() => {
    if (cal?.status !== "running") return;
    const t = setInterval(async () => {
      const res = await fetch(`${API}/api/calibrate/status`);
      if (res.ok) {
        const d = await res.json();
        setCal(d);
        if (d.status !== "running") { setRunning(false); clearInterval(t); }
      }
    }, 3000);
    return () => clearInterval(t);
  }, [cal?.status]);

  async function handleRun() {
    setRunning(true);
    setMsg("");
    try {
      const res = await fetch(`${API}/api/calibrate/run`, { method: "POST" });
      const d = await res.json();
      setMsg(d.message || "Calibration started.");
      setCal((c: any) => ({ ...c, status: "running" }));
    } catch { setRunning(false); setMsg("Error starting calibration."); }
  }

  async function handleReset() {
    if (!confirm("Reset all monthly correction factors to 1.0 (neutral)? This removes the current calibration.")) return;
    setResetting(true);
    setMsg("");
    try {
      const res = await fetch(`${API}/api/calibrate/reset`, { method: "POST" });
      const d = await res.json();
      setMsg(d.message || "Reset complete.");
      await load();
    } catch { setMsg("Error resetting calibration."); }
    setResetting(false);
  }

  if (loading) return <div className="flex items-center justify-center py-16"><Loader2 className="w-8 h-8 animate-spin text-emerald-500" /></div>;

  const isRunning  = cal?.status === "running" || running;
  const notRun     = cal?.status === "not_run";
  const suspicious = cal?.suspicious;

  return (
    <div className="space-y-5 max-w-2xl">
      {/* Status card */}
      <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-6">
        <div className="flex items-center gap-2 mb-4">
          <div className="w-8 h-8 rounded-lg bg-purple-500/10 flex items-center justify-center">
            <RefreshCw className="w-4 h-4 text-purple-400" />
          </div>
          <h2 className="font-semibold text-white">Irradiance Calibration</h2>
          {isRunning && <span className="ml-auto text-xs bg-amber-500/10 text-amber-400 border border-amber-500/20 px-2 py-0.5 rounded-full flex items-center gap-1"><Loader2 className="w-3 h-3 animate-spin" /> Running…</span>}
          {!isRunning && !notRun && suspicious && <span className="ml-auto text-xs bg-red-500/10 text-red-400 border border-red-500/20 px-2 py-0.5 rounded-full flex items-center gap-1"><AlertTriangle className="w-3 h-3" /> Anomalous factors detected</span>}
          {!isRunning && !notRun && !suspicious && <span className="ml-auto text-xs bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 px-2 py-0.5 rounded-full">✓ OK</span>}
        </div>

        <p className="text-slate-400 text-sm mb-4">
          Monthly correction factors align the expected-power model with your real production data.
          Each factor should be between 0.75 and 1.30 — outside this range usually means the calibration ran with insufficient data.
        </p>

        {notRun ? (
          <div className="bg-slate-800/50 rounded-xl p-4 text-slate-400 text-sm">No calibration file found. Click <strong className="text-white">Re-run Calibration</strong> to start. You need at least 30 days of inverter data.</div>
        ) : (
          <div className="space-y-3">
            <div className="flex flex-wrap gap-2 text-xs">
              <span className="text-slate-500">Winner source:</span>
              <span className="font-medium text-white capitalize">{cal?.winner ?? "—"}</span>
              <span className="text-slate-600 mx-1">·</span>
              <span className="text-slate-500">Age:</span>
              <span className="font-medium text-white">{cal?.age_days != null ? `${cal.age_days} days` : "—"}</span>
              {cal?.age_days > 25 && <span className="text-amber-400">(re-run recommended)</span>}
            </div>
            {suspicious && (
              <div className="bg-red-500/5 border border-red-500/20 rounded-xl p-3 text-sm text-red-300">
                <strong>Warning:</strong> One or more months have factors outside the 0.70–1.40 range. This inflates or deflates expected power, causing incorrect Performance Ratio calculations. Click <strong>Reset to Neutral</strong> then re-run when you have 30+ days of data.
              </div>
            )}
            <div className="grid grid-cols-4 gap-2">
              {(cal?.factors ?? []).map((f: any) => (
                <div key={f.month} className={`rounded-xl p-2.5 text-center border ${f.suspicious ? "border-red-500/30 bg-red-500/5" : "border-slate-700 bg-slate-800/40"}`}>
                  <div className="text-xs text-slate-400 mb-0.5">{f.month_name}</div>
                  <div className={`text-sm font-bold font-mono ${f.suspicious ? "text-red-400" : "text-white"}`}>{f.factor.toFixed(3)}</div>
                  {f.suspicious && <div className="text-xs text-red-400 mt-0.5">⚠</div>}
                </div>
              ))}
            </div>
          </div>
        )}

        {msg && <p className="text-emerald-400 text-sm mt-3">{msg}</p>}
      </div>

      {/* Actions */}
      <div className="flex flex-col sm:flex-row gap-3">
        <button onClick={handleRun} disabled={isRunning}
          className="flex-1 flex items-center justify-center gap-2 px-5 py-3 rounded-xl font-medium text-sm bg-emerald-500 hover:bg-emerald-400 text-white disabled:opacity-50 transition-all">
          {isRunning ? <><Loader2 className="w-4 h-4 animate-spin" /> Running…</> : <><RefreshCw className="w-4 h-4" /> Re-run Calibration</>}
        </button>
        <button onClick={handleReset} disabled={isRunning || resetting}
          className="flex-1 flex items-center justify-center gap-2 px-5 py-3 rounded-xl font-medium text-sm border border-slate-700 text-slate-300 hover:text-white hover:border-slate-500 disabled:opacity-50 transition-all">
          {resetting ? <><Loader2 className="w-4 h-4 animate-spin" /> Resetting…</> : <><RotateCcw className="w-4 h-4" /> Reset to Neutral (1.0)</>}
        </button>
      </div>

      <div className="bg-slate-900/40 border border-slate-800 rounded-xl p-4 text-xs text-slate-500 space-y-1">
        <p><strong className="text-slate-400">Re-run Calibration:</strong> Compares PVGIS-SARAH3, Open-Meteo ERA5, and VEDAS ISRO against your actual production to find the best-fit irradiance source. Takes ~30 seconds. Needs 30+ days of InfluxDB data.</p>
        <p><strong className="text-slate-400">Reset to Neutral:</strong> Sets all 12 monthly factors to 1.0. Expected power will use raw irradiance with no correction — use this to stop bad calibration from distorting your Performance Ratio.</p>
      </div>
    </div>
  );
}

const TABS = [
  { id: "system",        label: "System",       icon: "⚙️" },
  { id: "calibration",   label: "Calibration",  icon: "📡" },
  { id: "alerts",        label: "Alert Config", icon: "🔔" },
];

export default function SettingsPage() {
  const [active, setActive] = useState("system");

  return (
    <div className="space-y-5 max-w-4xl">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold" style={{ color: "var(--card-value)" }}>Settings</h1>
          <p className="text-sm mt-0.5" style={{ color: "var(--card-sub)" }}>
            System configuration · display preferences · alert channels
          </p>
        </div>
        <PageTabs tabs={TABS} active={active} onChange={setActive} />
      </div>

      <TabPanel id="system"       active={active}><SystemSettings /></TabPanel>
      <TabPanel id="calibration"  active={active}><CalibrationSettings /></TabPanel>
      <TabPanel id="alerts"       active={active}><AlertsPage /></TabPanel>
    </div>
  );
}
