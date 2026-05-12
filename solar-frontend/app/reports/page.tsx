"use client";

import { useEffect, useState } from "react";
import { FileText, Send, Settings, CheckCircle2, Bot } from "lucide-react";

export default function ReportsPage() {
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [triggering, setTriggering] = useState(false);
  const [message, setMessage] = useState("");

  useEffect(() => {
    async function fetchData() {
      try {
        const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL ?? ""}/api/reports`);
        if (res.ok) {
          const json = await res.json();
          setData(json.data);
        }
      } catch (e) {
        console.error("Failed to fetch reports data", e);
      } finally {
        setLoading(false);
      }
    }
    fetchData();
  }, []);

  const triggerReport = async (type: string) => {
    setTriggering(true);
    setMessage("");
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL ?? ""}/api/reports/generate?report_type=${type}`, {
        method: 'POST'
      });
      if (res.ok) {
        const json = await res.json();
        setMessage(json.message);
      }
    } catch (e) {
      console.error(e);
      setMessage("Failed to trigger report.");
    } finally {
      setTriggering(false);
      setTimeout(() => setMessage(""), 5000);
    }
  };

  if (loading) return <div className="flex items-center justify-center h-64"><div className="animate-spin rounded-full h-12 w-12 border-t-2 border-b-2 border-emerald-400" /></div>;
  if (!data) return <div>No data available</div>;

  return (
    <div className="space-y-6 max-w-5xl mx-auto">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold">Automated Reports</h1>
          <p className="text-[var(--text-secondary)] mt-1">Configure and generate intelligence reports</p>
        </div>
      </div>

      {message && (
        <div className="bg-emerald-500/10 border border-emerald-500/20 text-emerald-400 p-4 rounded-xl flex items-center gap-2 font-medium">
          <CheckCircle2 className="w-5 h-5" />
          {message}
        </div>
      )}

      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <div className="space-y-6">
          <div className="themed-card p-6">
            <h2 className="text-xl font-semibold mb-4 flex items-center gap-2">
              <Bot className="w-5 h-5 text-blue-400" />
              Manual Generation
            </h2>
            <div className="space-y-3">
              <button 
                onClick={() => triggerReport('daily')}
                disabled={triggering}
                className="w-full flex items-center justify-between p-4 rounded-xl bg-[var(--bg-hover)] border border-[var(--bg-border)] hover:border-blue-500/50 transition-colors disabled:opacity-50"
              >
                <div className="text-left">
                  <div className="font-semibold">Daily Telegram Summary</div>
                  <div className="text-xs text-[var(--text-secondary)] mt-1">Sends today's output and anomalies to Telegram immediately.</div>
                </div>
                <Send className="w-4 h-4 text-[var(--text-muted)]" />
              </button>

              <button 
                onClick={() => triggerReport('monthly')}
                disabled={triggering}
                className="w-full flex items-center justify-between p-4 rounded-xl bg-[var(--bg-hover)] border border-[var(--bg-border)] hover:border-emerald-500/50 transition-colors disabled:opacity-50"
              >
                <div className="text-left">
                  <div className="font-semibold">Monthly PDF Report</div>
                  <div className="text-xs text-[var(--text-secondary)] mt-1">Compiles PDF with full metrics and expected vs actual.</div>
                </div>
                <Send className="w-4 h-4 text-[var(--text-muted)]" />
              </button>
            </div>
          </div>

          <div className="themed-card p-6">
            <h2 className="text-xl font-semibold mb-4 flex items-center gap-2">
              <Settings className="w-5 h-5 text-amber-400" />
              Configuration
            </h2>
            <div className="space-y-4">
              {Object.entries(data.configurations).map(([key, value]) => (
                <div key={key} className="flex items-center justify-between">
                  <span className="text-sm font-medium capitalize">{key.replace(/_/g, ' ')}</span>
                  <div className={`w-10 h-5 rounded-full relative cursor-pointer ${value ? 'bg-emerald-500' : 'bg-slate-600'}`}>
                    <div className={`absolute top-0.5 w-4 h-4 rounded-full bg-white transition-all ${value ? 'right-0.5' : 'left-0.5'}`} />
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>

        <div className="themed-card p-6">
          <h2 className="text-xl font-semibold mb-4">Recent Dispatches</h2>
          <div className="space-y-4">
            {data.recent_reports.map((report: any) => (
              <div key={report.id} className="flex items-start gap-4 p-3 rounded-lg hover:bg-[var(--bg-hover)] transition-colors">
                <div className="p-2 bg-[var(--bg-base)] rounded-lg border border-[var(--bg-border)]">
                  <FileText className="w-5 h-5 text-[var(--text-secondary)]" />
                </div>
                <div className="flex-1">
                  <div className="flex justify-between items-start">
                    <div className="font-semibold text-sm">{report.type}</div>
                    <div className="text-xs text-[var(--text-muted)]">{new Date(report.date).toLocaleDateString()}</div>
                  </div>
                  <div className="flex items-center gap-2 mt-1">
                    <span className="text-xs bg-blue-500/10 text-blue-400 px-2 py-0.5 rounded">Via {report.destination}</span>
                    <span className="text-xs text-emerald-400 flex items-center gap-1"><CheckCircle2 className="w-3 h-3"/> {report.status}</span>
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}
