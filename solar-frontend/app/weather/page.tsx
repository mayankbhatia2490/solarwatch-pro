"use client";

import { useEffect, useState } from "react";
import { Cloud, Sun, Droplets, Wind, Zap, Thermometer, MapPin, Sunrise, Sunset } from "lucide-react";

export default function WeatherPage() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchData() {
      try {
        const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL ?? ""}/api/weather`);
        if (res.ok) {
          const json = await res.json();
          setData(json);
        }
      } catch (e) {
        console.error("Failed to fetch weather data", e);
      } finally {
        setLoading(false);
      }
    }
    fetchData();
    const interval = setInterval(fetchData, 5 * 60 * 1000); // refresh every 5 min
    return () => clearInterval(interval);
  }, []);

  if (loading) return <div className="flex items-center justify-center h-64"><div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-emerald-400" /></div>;
  if (!data || !data.data) return <div className="p-6 text-[var(--text-muted)]">Weather data unavailable</div>;

  const current = data.data.current;
  const location = data.location;
  const daily = data.data.daily || {};

  const sunrise = daily.sunrise?.[0] ? new Date(daily.sunrise[0]).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: true, timeZone: "Asia/Kolkata" }) : "--";
  const sunset = daily.sunset?.[0] ? new Date(daily.sunset[0]).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit", hour12: true, timeZone: "Asia/Kolkata" }) : "--";
  const uvMax = daily.uv_index_max?.[0] ?? "--";

  const capacity_kw = ((data.data.system_capacity_w || 3500) / 1000).toFixed(1);
  // expected_power_w and efficiency_drop_pct are null when weather API is unavailable
  const expectedW: number | null = data.data.expected_power_w ?? null;
  const actualW = data.data.actual_power_w ?? 0;
  const effDrop: number | null = data.data.efficiency_drop_pct ?? null;
  const pr = ((data.data.performance_ratio_used || 0.78) * 100).toFixed(0);

  // Sky condition label
  const cloudPct = current.cloud_cover ?? 0;
  const skyLabel = cloudPct < 15 ? "☀️ Clear" : cloudPct < 40 ? "🌤️ Partly Cloudy" : cloudPct < 70 ? "⛅ Mostly Cloudy" : "☁️ Overcast";

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-3xl font-bold">Weather Correlation</h1>
          <p className="text-[var(--text-secondary)] mt-1">Live solar irradiance & power correlation for your site</p>
        </div>
        <div className="flex items-center gap-2 text-sm text-[var(--text-muted)] themed-card px-3 py-2">
          <MapPin className="w-4 h-4 text-emerald-400" />
          <span>{location?.name ?? "Karnal, Haryana"}</span>
          <span className="text-[var(--text-muted)]">• {location?.latitude?.toFixed(2)}°N, {location?.longitude?.toFixed(2)}°E</span>
        </div>
      </div>

      {/* Current Conditions — 6 cards */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
        <div className="themed-card p-4 col-span-1">
          <div className="flex items-center gap-2 mb-2">
            <div className="p-1.5 rounded-lg bg-[var(--bg-hover)] text-amber-500"><Sun className="w-4 h-4" /></div>
            <div className="text-xs font-medium text-[var(--text-secondary)]">Direct Irr.</div>
          </div>
          <div className="text-xl font-bold">{current.direct_radiation ?? "--"} <span className="text-xs font-normal text-[var(--text-muted)]">W/m²</span></div>
        </div>

        <div className="themed-card p-4 col-span-1">
          <div className="flex items-center gap-2 mb-2">
            <div className="p-1.5 rounded-lg bg-[var(--bg-hover)] text-yellow-300"><Sun className="w-4 h-4" /></div>
            <div className="text-xs font-medium text-[var(--text-secondary)]">Diffuse Irr.</div>
          </div>
          <div className="text-xl font-bold">{current.diffuse_radiation ?? "--"} <span className="text-xs font-normal text-[var(--text-muted)]">W/m²</span></div>
        </div>

        <div className="themed-card p-4 col-span-1">
          <div className="flex items-center gap-2 mb-2">
            <div className="p-1.5 rounded-lg bg-[var(--bg-hover)] text-blue-400"><Cloud className="w-4 h-4" /></div>
            <div className="text-xs font-medium text-[var(--text-secondary)]">Cloud Cover</div>
          </div>
          <div className="text-xl font-bold">{cloudPct}%</div>
          <div className="text-xs text-[var(--text-muted)] mt-1">{skyLabel}</div>
        </div>

        <div className="themed-card p-4 col-span-1">
          <div className="flex items-center gap-2 mb-2">
            <div className="p-1.5 rounded-lg bg-[var(--bg-hover)] text-red-400"><Thermometer className="w-4 h-4" /></div>
            <div className="text-xs font-medium text-[var(--text-secondary)]">Temperature</div>
          </div>
          <div className="text-xl font-bold">{current.temperature_2m ?? "--"}°C</div>
          <div className="text-xs text-[var(--text-muted)] mt-1">Feels {current.apparent_temperature ?? "--"}°C</div>
        </div>

        <div className="themed-card p-4 col-span-1">
          <div className="flex items-center gap-2 mb-2">
            <div className="p-1.5 rounded-lg bg-[var(--bg-hover)] text-cyan-400"><Droplets className="w-4 h-4" /></div>
            <div className="text-xs font-medium text-[var(--text-secondary)]">Humidity</div>
          </div>
          <div className="text-xl font-bold">{current.relative_humidity_2m ?? "--"}%</div>
        </div>

        <div className="themed-card p-4 col-span-1">
          <div className="flex items-center gap-2 mb-2">
            <div className="p-1.5 rounded-lg bg-[var(--bg-hover)] text-slate-400"><Wind className="w-4 h-4" /></div>
            <div className="text-xs font-medium text-[var(--text-secondary)]">Wind</div>
          </div>
          <div className="text-xl font-bold">{current.wind_speed_10m ?? "--"} <span className="text-xs font-normal text-[var(--text-muted)]">km/h</span></div>
        </div>
      </div>

      {/* Sunrise / Sunset / UV row */}
      <div className="grid grid-cols-3 gap-4">
        <div className="themed-card p-4 flex items-center gap-4">
          <div className="p-2 rounded-xl bg-amber-500/10 text-amber-500"><Sunrise className="w-6 h-6" /></div>
          <div>
            <div className="text-xs text-[var(--text-muted)]">Sunrise</div>
            <div className="text-lg font-bold">{sunrise}</div>
          </div>
        </div>
        <div className="themed-card p-4 flex items-center gap-4">
          <div className="p-2 rounded-xl bg-orange-500/10 text-orange-400"><Sunset className="w-6 h-6" /></div>
          <div>
            <div className="text-xs text-[var(--text-muted)]">Sunset</div>
            <div className="text-lg font-bold">{sunset}</div>
          </div>
        </div>
        <div className="themed-card p-4 flex items-center gap-4">
          <div className="p-2 rounded-xl bg-purple-500/10 text-purple-400">
            <span className="text-xl font-bold">UV</span>
          </div>
          <div>
            <div className="text-xs text-[var(--text-muted)]">UV Index (max today)</div>
            <div className="text-lg font-bold">{uvMax} <span className="text-sm font-normal text-[var(--text-muted)]">{Number(uvMax) >= 8 ? "Very High" : Number(uvMax) >= 6 ? "High" : Number(uvMax) >= 3 ? "Moderate" : "Low"}</span></div>
          </div>
        </div>
      </div>

      {/* Power Potential vs Actual */}
      <div className="themed-card p-6 border-l-4 border-l-emerald-500">
        <h2 className="text-xl font-bold mb-1">Power Potential vs Actual</h2>
        <p className="text-sm text-[var(--text-muted)] mb-5">Based on KSY 3.4kW-1Ph {capacity_kw}kW inverter · PR={pr}% · Location: Karnal</p>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div className="bg-[var(--bg-hover)] p-4 rounded-xl">
            <div className="text-sm text-[var(--text-secondary)] mb-1">Total Irradiance</div>
            <div className="text-3xl font-bold text-amber-400">{current.total_irradiance ?? (current.direct_radiation + current.diffuse_radiation)} <span className="text-sm font-normal">W/m²</span></div>
          </div>
          <div className="bg-[var(--bg-hover)] p-4 rounded-xl">
            <div className="text-sm text-[var(--text-secondary)] mb-1">Expected Power (Weather-Adj.)</div>
            {expectedW !== null ? (
              <>
                <div className="text-3xl font-bold text-amber-400">{expectedW} <span className="text-sm font-normal">W</span></div>
                <div className="text-xs text-[var(--text-muted)] mt-1">{capacity_kw}kW × (Irr/1000) × PR</div>
              </>
            ) : (
              <>
                <div className="text-3xl font-bold text-slate-500">—</div>
                <div className="text-xs text-[var(--text-muted)] mt-1">Unavailable — weather data offline</div>
              </>
            )}
          </div>
          <div className="bg-[var(--bg-hover)] p-4 rounded-xl">
            <div className="text-sm text-[var(--text-secondary)] mb-1">Actual Power (Inverter Live)</div>
            <div className="text-3xl font-bold text-emerald-400">{actualW} <span className="text-sm font-normal">W</span></div>
          </div>
        </div>

        {/* Efficiency gap — only shown when real expected_power_w is available */}
        {expectedW !== null && expectedW > 100 && effDrop !== null && (
          <div className="mt-4 flex items-center gap-3">
            <Zap className="w-5 h-5 text-purple-400" />
            <span className="text-sm text-[var(--text-secondary)]">Performance Gap:</span>
            <span className={`text-lg font-bold ${effDrop > 20 ? "text-red-400" : effDrop > 10 ? "text-amber-400" : "text-emerald-400"}`}>
              {effDrop}% {effDrop > 20 ? "⚠ Check panels/shading" : effDrop > 10 ? "↓ Minor loss" : "✓ Normal"}
            </span>
          </div>
        )}
        {(expectedW === null || effDrop === null) && (
          <div className="mt-4 flex items-center gap-3">
            <Zap className="w-5 h-5 text-slate-500" />
            <span className="text-sm text-[var(--text-muted)]">Performance gap unavailable — weather data offline</span>
          </div>
        )}
      </div>
    </div>
  );
}
