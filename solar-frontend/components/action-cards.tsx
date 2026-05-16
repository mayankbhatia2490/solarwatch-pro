"use client";

import { useEffect, useState } from "react";
import { Sparkles, ArrowRight, Zap, Thermometer, Wind, Wrench, Calendar, AlertCircle } from "lucide-react";

interface Suggestion {
  rank: number;
  category: string;
  title: string;
  problem: string;
  solution: string;
  expected_gain_pct: number;
  expected_gain_inr_monthly: number;
  cost_inr: number;
  payback_months: number;
  effort: "easy" | "medium" | "complex";
  diy: boolean;
}

const CACHE_KEY = "sw_suggestions_v1";
const CACHE_TTL = 4 * 60 * 60 * 1000;

const CATEGORY_ICON: Record<string, React.ReactNode> = {
  thermal:     <Thermometer className="w-4 h-4" />,
  soiling:     <Wind className="w-4 h-4" />,
  shading:     <AlertCircle className="w-4 h-4" />,
  wiring:      <Zap className="w-4 h-4" />,
  seasonal:    <Calendar className="w-4 h-4" />,
  operational: <Wrench className="w-4 h-4" />,
};

const EFFORT_COLOR: Record<string, string> = {
  easy:    "text-emerald-400 border-emerald-500/30 bg-emerald-500/10",
  medium:  "text-amber-400 border-amber-500/30 bg-amber-500/10",
  complex: "text-red-400 border-red-500/30 bg-red-500/10",
};

export function ActionCards() {
  const [items, setItems] = useState<Suggestion[]>([]);

  useEffect(() => {
    try {
      const raw = localStorage.getItem(CACHE_KEY);
      if (!raw) return;
      const parsed = JSON.parse(raw);
      if (Date.now() - parsed.fetched_ms > CACHE_TTL) return;
      // Show only easy items or those with payback ≤ 12 months — true quick wins
      const urgent: Suggestion[] = (parsed.suggestions ?? []).filter(
        (s: Suggestion) => s.effort === "easy" || s.payback_months <= 12
      ).slice(0, 3);
      setItems(urgent);
    } catch {
      /* ignore corrupt cache */
    }
  }, []);

  // Fetch fresh if cache is empty
  useEffect(() => {
    if (items.length > 0) return;
    fetch(`${process.env.NEXT_PUBLIC_API_URL ?? ""}/api/ai/suggestions`)
      .then(r => r.ok ? r.json() : null)
      .then(json => {
        if (!json?.suggestions) return;
        const cached = { suggestions: json.suggestions, fetched_ms: Date.now() };
        try { localStorage.setItem(CACHE_KEY, JSON.stringify(cached)); } catch {}
        const urgent: Suggestion[] = json.suggestions.filter(
          (s: Suggestion) => s.effort === "easy" || s.payback_months <= 12
        ).slice(0, 3);
        setItems(urgent);
      })
      .catch(() => {});
  }, [items.length]);

  if (items.length === 0) return null;

  return (
    <div>
      <div className="flex items-center justify-between mb-3">
        <div className="flex items-center gap-2">
          <Sparkles className="w-4 h-4 text-violet-400" />
          <span className="text-sm font-semibold" style={{ color: "var(--card-title)" }}>
            Actions needed
          </span>
          <span className="text-xs px-2 py-0.5 rounded-full bg-violet-500/15 text-violet-400">
            {items.length} quick win{items.length > 1 ? "s" : ""}
          </span>
        </div>
        <a
          href="/analysis"
          className="flex items-center gap-1 text-xs hover:underline"
          style={{ color: "var(--text-muted)" }}
        >
          All suggestions <ArrowRight className="w-3 h-3" />
        </a>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
        {items.map((s, i) => (
          <div
            key={i}
            className={`rounded-xl border p-4 flex flex-col gap-2 ${EFFORT_COLOR[s.effort]}`}
          >
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2 opacity-80">
                {CATEGORY_ICON[s.category] ?? <Wrench className="w-4 h-4" />}
                <span className="text-xs font-semibold uppercase tracking-wide opacity-70">
                  {s.category}
                </span>
              </div>
              <span className="text-xs font-bold">+{s.expected_gain_pct}% PR</span>
            </div>

            <p className="text-sm font-semibold leading-snug" style={{ color: "var(--card-value)" }}>
              {s.title}
            </p>
            <p className="text-xs leading-relaxed" style={{ color: "var(--text-secondary)" }}>
              {s.problem}
            </p>

            <div className="flex items-center justify-between mt-auto pt-1 text-xs" style={{ color: "var(--text-muted)" }}>
              <span>₹{s.expected_gain_inr_monthly}/mo saved</span>
              <span>{s.diy ? "✅ DIY" : "👷 Pro"}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
