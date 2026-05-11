"use client";

import { useEffect, useState } from "react";
import { AlertTriangle, Cpu, Zap, Activity, Clock, ServerCrash, CheckCircle2 } from "lucide-react";

export default function AnomaliesPage() {
  const [anomalies, setAnomalies] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function fetchData() {
      try {
        const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL || "http://localhost:8090"}/api/anomalies`);
        if (res.ok) {
          const json = await res.json();
          setAnomalies(json.data || []);
        }
      } catch (e) {
        console.error("Failed to fetch anomalies", e);
      } finally {
        setLoading(false);
      }
    }
    fetchData();
  }, []);

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Anomaly Detection</h1>
          <p className="text-[var(--text-secondary)] mt-1">Timeline of hardware faults and intelligence-driven alerts</p>
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center h-64"><div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-emerald-400" /></div>
      ) : anomalies.length === 0 ? (
        <div className="glass-card rounded-2xl p-12 text-center flex flex-col items-center">
          <div className="w-16 h-16 bg-emerald-500/10 rounded-full flex items-center justify-center mb-4">
            <CheckCircle2 className="w-8 h-8 text-emerald-500" />
          </div>
          <h2 className="text-xl font-semibold mb-2">System Healthy</h2>
          <p className="text-[var(--text-secondary)]">No anomalies or hardware faults detected in the last 7 days.</p>
        </div>
      ) : (
        <div className="relative border-l-2 border-[var(--bg-border)] ml-4 pl-8 space-y-8">
          {anomalies.map((item, i) => (
            <div key={i} className="relative">
              {/* Timeline dot */}
              <div className={`absolute -left-[41px] top-4 w-5 h-5 rounded-full border-4 border-[var(--bg-base)] flex items-center justify-center ${
                item.severity === 'critical' ? 'bg-red-500' : 'bg-amber-500'
              }`} />
              
              <div className="themed-card-2 p-5 sm:p-6 transition-all hover:-translate-y-1 hover:shadow-lg">
                <div className="flex flex-col sm:flex-row sm:items-start justify-between gap-4">
                  
                  {/* Left content */}
                  <div className="space-y-3">
                    <div className="flex items-center gap-3">
                      <span className={`px-2.5 py-1 text-xs font-semibold rounded-full ${
                        item.severity === 'critical' ? 'bg-red-500/10 text-red-500 border border-red-500/20' : 
                        'bg-amber-500/10 text-amber-500 border border-amber-500/20'
                      }`}>
                        {item.severity.toUpperCase()}
                      </span>
                      <span className="text-sm font-medium text-[var(--text-secondary)] flex items-center gap-1.5">
                        {item.source === 'Hardware' ? <ServerCrash className="w-4 h-4" /> : <Cpu className="w-4 h-4" />}
                        {item.source}
                      </span>
                      <span className="text-sm text-[var(--text-muted)] flex items-center gap-1">
                        <Clock className="w-3.5 h-3.5" />
                        {new Date(item.timestamp).toLocaleString()}
                      </span>
                    </div>

                    <div>
                      <h3 className="text-lg font-bold">{item.title}</h3>
                      <p className="text-[var(--text-secondary)] mt-1">{item.description}</p>
                    </div>

                    <div className="flex flex-wrap gap-4 pt-2">
                      <div className="flex items-center gap-2">
                        <div className="w-8 h-8 rounded-lg bg-[var(--bg-hover)] flex items-center justify-center">
                          <Activity className="w-4 h-4 text-[var(--text-secondary)]" />
                        </div>
                        <div>
                          <div className="text-xs text-[var(--text-muted)]">Parameter</div>
                          <div className="text-sm font-semibold">{item.parameter}</div>
                        </div>
                      </div>
                      
                      {item.impact_inr > 0 && (
                        <div className="flex items-center gap-2">
                          <div className="w-8 h-8 rounded-lg bg-red-500/10 flex items-center justify-center">
                            <span className="text-sm text-red-500">₹</span>
                          </div>
                          <div>
                            <div className="text-xs text-[var(--text-muted)]">Est. Impact</div>
                            <div className="text-sm font-semibold text-red-400">~₹{item.impact_inr}/hour</div>
                          </div>
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Right actions */}
                  <div className="bg-[var(--bg-hover)] rounded-xl p-4 sm:w-64 border border-[var(--bg-border)]">
                    <div className="text-xs text-[var(--text-muted)] mb-1">Recommended Action</div>
                    <div className="text-sm font-medium">{item.action}</div>
                    
                    <div className="flex gap-2 mt-4">
                      <button className="flex-1 py-1.5 px-3 bg-[var(--sidebar-active)] text-emerald-500 rounded-lg text-xs font-semibold hover:bg-emerald-500/20 transition-colors">
                        Mark Resolved
                      </button>
                      <button className="py-1.5 px-3 border border-[var(--bg-border)] text-[var(--text-secondary)] rounded-lg text-xs font-semibold hover:bg-[var(--bg-hover)] transition-colors">
                        Share
                      </button>
                    </div>
                  </div>

                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
