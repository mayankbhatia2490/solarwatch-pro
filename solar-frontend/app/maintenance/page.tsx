"use client";

import { useEffect, useState } from "react";
import { Wrench, Calendar, Info, TrendingUp, AlertTriangle } from "lucide-react";

export default function MaintenancePage() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchData() {
      try {
        const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL ?? ""}/api/maintenance`);
        if (res.ok) {
          const json = await res.json();
          setData(json.data);
        }
      } catch (e) {
        console.error("Failed to fetch maintenance data", e);
      } finally {
        setLoading(false);
      }
    }
    fetchData();
  }, []);

  if (loading) return <div className="flex items-center justify-center h-64"><div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-emerald-400" /></div>;
  if (!data) return <div>No data available</div>;

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Predictive Maintenance</h1>
          <p className="text-[var(--text-secondary)] mt-1">AI-driven hardware heuristics and scheduling</p>
        </div>
        <div className="text-right">
          <div className="text-sm text-[var(--text-secondary)]">Next Recommended Service</div>
          <div className="text-xl font-bold text-emerald-400 flex items-center justify-end gap-2">
            <Calendar className="w-5 h-5" />
            {data.days_to_service} Days
          </div>
        </div>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="space-y-4">
          <h2 className="text-xl font-semibold">Active Predictions</h2>
          {data.predictions.map((pred: any) => (
            <div key={pred.id} className="themed-card-2 p-5 border-l-4 border-l-amber-500">
              <div className="flex justify-between items-start mb-3">
                <h3 className="font-bold text-lg flex items-center gap-2">
                  <AlertTriangle className="w-5 h-5 text-amber-500" />
                  {pred.title}
                </h3>
                <span className="text-xs px-2 py-1 bg-amber-500/10 text-amber-500 rounded-full font-medium">
                  {pred.confidence}% Confident
                </span>
              </div>
              <p className="text-sm text-[var(--text-secondary)] mb-4">{pred.trend}</p>
              
              <div className="bg-[var(--bg-hover)] rounded-xl p-3 grid grid-cols-2 gap-4 mb-4 text-sm">
                <div>
                  <div className="text-[var(--text-muted)] text-xs">Cost to Fix</div>
                  <div className="font-semibold text-red-400">₹{pred.fix_cost_inr}</div>
                </div>
                <div>
                  <div className="text-[var(--text-muted)] text-xs">Projected Savings</div>
                  <div className="font-semibold text-emerald-400">₹{pred.revenue_saved_inr}/mo</div>
                </div>
              </div>
              
              <button className="w-full py-2 bg-[var(--sidebar-active)] text-[var(--text-primary)] rounded-lg text-sm font-semibold hover:bg-[var(--bg-hover)] transition-colors border border-[var(--bg-border)]">
                {pred.action}
              </button>
            </div>
          ))}
        </div>

        <div className="space-y-4">
          <h2 className="text-xl font-semibold">Service History</h2>
          <div className="themed-card p-6 relative">
            <div className="absolute left-9 top-10 bottom-10 w-0.5 bg-[var(--bg-border)]" />
            <div className="space-y-6">
              {data.history.map((hist: any, i: number) => (
                <div key={i} className="relative flex gap-4">
                  <div className="w-6 h-6 rounded-full bg-[var(--bg-base)] border-2 border-emerald-500 flex-shrink-0 z-10" />
                  <div>
                    <div className="text-sm text-[var(--text-muted)]">{new Date(hist.date).toLocaleDateString()}</div>
                    <div className="font-semibold mt-1">{hist.action}</div>
                    <div className="text-sm text-[var(--text-secondary)] mt-1 flex items-center gap-1">
                      <TrendingUp className="w-4 h-4" /> {hist.outcome}
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
