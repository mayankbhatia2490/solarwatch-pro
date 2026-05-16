"use client";

import { useEffect, useState } from "react";
import { Sparkles, RefreshCw, Loader2, ChevronDown, ChevronUp, ExternalLink } from "lucide-react";

interface Suggestion {
  rank: number;
  category: string;
  title: string;
  problem: string;
  solution: string;
  expected_gain_pct: number;
  expected_gain_kwh_monthly: number;
  expected_gain_inr_monthly: number;
  cost_inr: number;
  payback_months: number;
  effort: "easy" | "medium" | "complex";
  diy: boolean;
  season: string;
}

interface CachedData {
  suggestions: Suggestion[];
  context: any;
  generated_at: string;
  fetched_ms: number;
}

const CACHE_KEY = "sw_suggestions_v1";
const CACHE_TTL = 4 * 60 * 60 * 1000; // 4 hours

function categoryLabel(cat: string): string {
  const map: Record<string, string> = {
    thermal:     "🌡️ Thermal",
    soiling:     "🧹 Soiling",
    shading:     "☁️ Shading",
    wiring:      "⚡ Wiring",
    seasonal:    "📅 Seasonal",
    operational: "🔧 Operational",
  };
  return map[cat] ?? cat;
}

function effortBadge(effort: string) {
  const styles: Record<string, string> = {
    easy:    "bg-emerald-500/15 text-emerald-500",
    medium:  "bg-amber-500/15 text-amber-500",
    complex: "bg-red-500/15 text-red-400",
  };
  return (
    <span className={`px-2 py-0.5 rounded-full text-xs font-medium ${styles[effort] ?? "bg-slate-500/20 text-slate-400"}`}>
      {effort}
    </span>
  );
}

function paybackColor(months: number): string {
  if (months <= 12) return "text-emerald-500";
  if (months <= 36) return "text-amber-500";
  return "text-slate-400";
}

export function SmartSuggestions() {
  const [data, setData]       = useState<CachedData | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError]     = useState<string | null>(null);
  const [expanded, setExpanded] = useState<number | null>(null);
  const [noKey, setNoKey]     = useState(false);

  function loadFromCache(): CachedData | null {
    try {
      const raw = localStorage.getItem(CACHE_KEY);
      if (!raw) return null;
      const parsed: CachedData = JSON.parse(raw);
      if (Date.now() - parsed.fetched_ms > CACHE_TTL) return null;
      return parsed;
    } catch {
      return null;
    }
  }

  async function fetchSuggestions(force = false) {
    if (!force) {
      const cached = loadFromCache();
      if (cached) { setData(cached); return; }
    }

    setLoading(true);
    setError(null);
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL ?? ""}/api/ai/suggestions`);
      const json = await res.json();
      if (!res.ok) {
        if (res.status === 503) { setNoKey(true); return; }
        setError(json.detail || "Failed to load suggestions");
        return;
      }
      const cached: CachedData = {
        suggestions:  json.suggestions,
        context:      json.context,
        generated_at: json.generated_at,
        fetched_ms:   Date.now(),
      };
      localStorage.setItem(CACHE_KEY, JSON.stringify(cached));
      setData(cached);
    } catch {
      setError("Could not reach API");
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { fetchSuggestions(); }, []);

  // Don't render anything if no Gemini key — silently hide the widget
  if (noKey) return null;

  const ageMin = data
    ? Math.round((Date.now() - data.fetched_ms) / 60000)
    : null;

  return (
    <div className="glass-card rounded-2xl p-5">
      {/* Header */}
      <div className="flex items-center justify-between mb-1 flex-wrap gap-2">
        <div className="flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-violet-400" />
          <h2 className="font-semibold" style={{ color: "var(--card-title)" }}>
            Smart Improvement Suggestions
          </h2>
          <span className="text-xs px-2 py-0.5 rounded-full bg-violet-500/15 text-violet-400 font-medium">
            AI · Gemini
          </span>
        </div>
        <button
          onClick={() => fetchSuggestions(true)}
          disabled={loading}
          className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg border transition-colors hover:bg-[var(--bg-hover)] disabled:opacity-50"
          style={{ borderColor: "var(--bg-border)", color: "var(--text-secondary)" }}
          title="Refresh suggestions from Gemini"
        >
          {loading
            ? <Loader2 className="w-3.5 h-3.5 animate-spin" />
            : <RefreshCw className="w-3.5 h-3.5" />}
          {loading ? "Analysing…" : "Refresh"}
        </button>
      </div>
      <p className="text-xs mb-4" style={{ color: "var(--card-sub)" }}>
        Based on live inverter temperature, 30-day PR and cleaning data · cached {ageMin != null ? `${ageMin}m ago` : "…"}
      </p>

      {/* Loading skeleton */}
      {loading && !data && (
        <div className="space-y-3">
          {[...Array(4)].map((_, i) => (
            <div key={i} className="skeleton h-14 rounded-xl" />
          ))}
        </div>
      )}

      {/* Error */}
      {error && (
        <div className="rounded-xl border border-red-500/30 bg-red-500/10 p-4 text-sm text-red-400">
          {error}
        </div>
      )}

      {/* Table */}
      {data && data.suggestions.length > 0 && (
        <>
          {/* Context strip */}
          {data.context && (
            <div className="flex flex-wrap gap-4 mb-3 text-xs" style={{ color: "var(--text-muted)" }}>
              {data.context.avg_inverter_temp_c != null &&
                <span>🌡️ Avg inverter temp: <strong style={{ color: "var(--card-value)" }}>{data.context.avg_inverter_temp_c}°C</strong></span>}
              {data.context.pr_30d_pct != null &&
                <span>📊 30d PR: <strong style={{ color: "var(--card-value)" }}>{data.context.pr_30d_pct}%</strong></span>}
              {data.context.days_since_clean < 900 &&
                <span>🧹 Last clean: <strong style={{ color: "var(--card-value)" }}>{data.context.days_since_clean}d ago</strong></span>}
            </div>
          )}

          {/* Desktop table */}
          <div className="hidden md:block overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="text-xs border-b" style={{ color: "var(--card-label)", borderColor: "var(--bg-border)" }}>
                  <th className="text-left py-2 pr-3 w-5">#</th>
                  <th className="text-left py-2 pr-3">Improvement</th>
                  <th className="text-left py-2 pr-3">Category</th>
                  <th className="text-right py-2 pr-3">PR gain</th>
                  <th className="text-right py-2 pr-3">Monthly saving</th>
                  <th className="text-right py-2 pr-3">Cost</th>
                  <th className="text-right py-2 pr-3">Payback</th>
                  <th className="text-center py-2 pr-3">Effort</th>
                  <th className="text-center py-2">DIY?</th>
                </tr>
              </thead>
              <tbody>
                {data.suggestions.map((s, i) => (
                  <>
                    <tr
                      key={i}
                      className="border-b cursor-pointer hover:bg-[var(--bg-hover)] transition-colors"
                      style={{ borderColor: "var(--bg-border)" }}
                      onClick={() => setExpanded(expanded === i ? null : i)}
                    >
                      <td className="py-3 pr-3 font-bold text-xs" style={{ color: "var(--text-muted)" }}>{s.rank}</td>
                      <td className="py-3 pr-3">
                        <div className="flex items-center gap-1.5">
                          <span className="font-semibold" style={{ color: "var(--card-value)" }}>{s.title}</span>
                          {expanded === i
                            ? <ChevronUp className="w-3 h-3 flex-shrink-0" style={{ color: "var(--text-muted)" }} />
                            : <ChevronDown className="w-3 h-3 flex-shrink-0" style={{ color: "var(--text-muted)" }} />}
                        </div>
                        <div className="text-xs mt-0.5" style={{ color: "var(--text-secondary)" }}>{s.season}</div>
                      </td>
                      <td className="py-3 pr-3 text-xs">{categoryLabel(s.category)}</td>
                      <td className="py-3 pr-3 text-right font-semibold text-emerald-500">+{s.expected_gain_pct}%</td>
                      <td className="py-3 pr-3 text-right">
                        <div className="font-semibold" style={{ color: "var(--card-value)" }}>₹{s.expected_gain_inr_monthly}/mo</div>
                        <div className="text-xs" style={{ color: "var(--text-muted)" }}>{s.expected_gain_kwh_monthly} kWh</div>
                      </td>
                      <td className="py-3 pr-3 text-right font-semibold" style={{ color: "var(--card-value)" }}>
                        ₹{s.cost_inr.toLocaleString("en-IN")}
                      </td>
                      <td className={`py-3 pr-3 text-right font-semibold ${paybackColor(s.payback_months)}`}>
                        {s.payback_months < 120 ? `${s.payback_months}m` : "—"}
                      </td>
                      <td className="py-3 pr-3 text-center">{effortBadge(s.effort)}</td>
                      <td className="py-3 text-center text-base">{s.diy ? "✅" : "👷"}</td>
                    </tr>
                    {expanded === i && (
                      <tr key={`${i}-detail`} style={{ borderColor: "var(--bg-border)" }}
                          className="border-b">
                        <td colSpan={9} className="pb-4 pt-2 pr-4">
                          <div className="rounded-xl p-4 space-y-2" style={{ background: "var(--bg-hover)" }}>
                            <div>
                              <span className="text-xs font-semibold" style={{ color: "var(--card-label)" }}>WHY: </span>
                              <span className="text-xs" style={{ color: "var(--text-secondary)" }}>{s.problem}</span>
                            </div>
                            <div>
                              <span className="text-xs font-semibold" style={{ color: "var(--card-label)" }}>HOW: </span>
                              <span className="text-xs" style={{ color: "var(--text-secondary)" }}>{s.solution}</span>
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </>
                ))}
              </tbody>
            </table>
          </div>

          {/* Mobile cards */}
          <div className="md:hidden space-y-3">
            {data.suggestions.map((s, i) => (
              <div
                key={i}
                className="rounded-xl border cursor-pointer transition-colors"
                style={{ borderColor: "var(--bg-border)", background: "var(--bg-surface)" }}
                onClick={() => setExpanded(expanded === i ? null : i)}
              >
                <div className="p-4">
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 flex-wrap">
                        <span className="font-semibold text-sm" style={{ color: "var(--card-value)" }}>
                          {s.rank}. {s.title}
                        </span>
                        {effortBadge(s.effort)}
                      </div>
                      <div className="text-xs mt-0.5">{categoryLabel(s.category)} · {s.season}</div>
                    </div>
                    {expanded === i
                      ? <ChevronUp className="w-4 h-4 flex-shrink-0 mt-0.5" style={{ color: "var(--text-muted)" }} />
                      : <ChevronDown className="w-4 h-4 flex-shrink-0 mt-0.5" style={{ color: "var(--text-muted)" }} />}
                  </div>
                  <div className="grid grid-cols-3 gap-3 mt-3 text-center">
                    <div>
                      <div className="text-sm font-bold text-emerald-500">+{s.expected_gain_pct}%</div>
                      <div className="text-xs" style={{ color: "var(--text-muted)" }}>PR gain</div>
                    </div>
                    <div>
                      <div className="text-sm font-bold" style={{ color: "var(--card-value)" }}>₹{s.expected_gain_inr_monthly}</div>
                      <div className="text-xs" style={{ color: "var(--text-muted)" }}>per month</div>
                    </div>
                    <div>
                      <div className={`text-sm font-bold ${paybackColor(s.payback_months)}`}>
                        {s.payback_months < 120 ? `${s.payback_months}m` : "—"}
                      </div>
                      <div className="text-xs" style={{ color: "var(--text-muted)" }}>payback</div>
                    </div>
                  </div>
                  {expanded === i && (
                    <div className="mt-3 pt-3 border-t space-y-2" style={{ borderColor: "var(--bg-border)" }}>
                      <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
                        <strong style={{ color: "var(--card-label)" }}>Why: </strong>{s.problem}
                      </p>
                      <p className="text-xs" style={{ color: "var(--text-secondary)" }}>
                        <strong style={{ color: "var(--card-label)" }}>How: </strong>{s.solution}
                      </p>
                      <p className="text-xs" style={{ color: "var(--text-muted)" }}>
                        Cost: ₹{s.cost_inr.toLocaleString("en-IN")} · {s.diy ? "✅ DIY" : "👷 Professional needed"}
                      </p>
                    </div>
                  )}
                </div>
              </div>
            ))}
          </div>

          <p className="text-xs mt-3" style={{ color: "var(--text-muted)" }}>
            Gains are estimates based on typical Karnal conditions. Actual results vary. Click any row for details.
          </p>
        </>
      )}
    </div>
  );
}
