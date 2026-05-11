"use client";
import { useState, useEffect, useCallback } from "react";
import { Bell, BotMessageSquare, Send, CheckCircle, XCircle, Loader2 } from "lucide-react";

const API = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8090";

type Status = "idle" | "loading" | "success" | "error";

function StatusBadge({ s, msg }: { s: Status; msg?: string }) {
  if (s === "idle") return null;
  if (s === "loading") return <span className="flex items-center gap-1 text-slate-400 text-sm"><Loader2 className="w-4 h-4 animate-spin" /> Sending…</span>;
  if (s === "success") return <span className="flex items-center gap-1 text-emerald-400 text-sm"><CheckCircle className="w-4 h-4" /> {msg || "Success!"}</span>;
  return <span className="flex items-center gap-1 text-red-400 text-sm"><XCircle className="w-4 h-4" /> {msg || "Failed"}</span>;
}

export default function AlertsPage() {
  const [testStatus, setTestStatus] = useState<Status>("idle");
  const [testMsg, setTestMsg] = useState("");
  const [detectStatus, setDetectStatus] = useState<Status>("idle");
  const [detectMsg, setDetectMsg] = useState("");
  const [chatId, setChatId] = useState<string | null>(null);
  const [chatIdInput, setChatIdInput] = useState("");

  const sendTest = async () => {
    setTestStatus("loading");
    try {
      const res = await fetch(`${API}/api/notifications/test`, { method: "POST" });
      const j = await res.json();
      if (res.ok && j.success) { setTestStatus("success"); setTestMsg("Message sent! Check Telegram."); }
      else { setTestStatus("error"); setTestMsg(j.detail || "Check bot token & chat ID."); }
    } catch { setTestStatus("error"); setTestMsg("API unreachable"); }
  };

  const detectChatId = async () => {
    setDetectStatus("loading");
    try {
      const res = await fetch(`${API}/api/notifications/detect-chat-id`);
      const j = await res.json();
      if (res.ok && j.chat_id) {
        setDetectStatus("success");
        setDetectMsg(`Chat ID: ${j.chat_id}`);
        setChatId(String(j.chat_id));
        setChatIdInput(String(j.chat_id));
      } else { setDetectStatus("error"); setDetectMsg("No messages found. Send /start to your bot first."); }
    } catch { setDetectStatus("error"); setDetectMsg("API unreachable"); }
  };

  const ALERT_TYPES = [
    { icon: "⚡", title: "Power Drop Alert", desc: "Triggered when output drops >30% unexpectedly during daylight", active: true },
    { icon: "🌡️", title: "High Temperature Alert", desc: "Triggered when inverter temperature exceeds 70°C", active: true },
    { icon: "🔌", title: "Grid Fault Alert", desc: "Triggered when grid voltage is outside 200–250V range", active: true },
    { icon: "☀️", title: "Daily Summary Report", desc: "Sent every evening with kWh, savings, and performance summary", active: true },
    { icon: "📈", title: "Production Milestone", desc: "Notified when you hit 1 MWh, 2 MWh, 5 MWh milestones", active: false },
  ];

  return (
    <div className="space-y-6 max-w-3xl mx-auto">
      <div>
        <h1 className="text-2xl font-bold text-white">Alerts & Notifications</h1>
        <p className="text-slate-400 text-sm mt-1">Telegram bot configuration and alert management</p>
      </div>

      {/* Telegram Setup */}
      <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-6">
        <div className="flex items-center gap-3 mb-5">
          <div className="w-10 h-10 rounded-xl bg-blue-500/10 flex items-center justify-center">
            <BotMessageSquare className="w-5 h-5 text-blue-400" />
          </div>
          <div>
            <h2 className="font-semibold text-white">Telegram Bot</h2>
            <p className="text-slate-400 text-xs">@Solarwatchpro_bot</p>
          </div>
          <div className="ml-auto flex items-center gap-2 px-3 py-1 rounded-full bg-emerald-500/10 border border-emerald-500/20">
            <span className="w-2 h-2 rounded-full bg-emerald-400 animate-pulse" />
            <span className="text-emerald-400 text-xs font-medium">Connected</span>
          </div>
        </div>

        <div className="space-y-4">
          {/* Step 1 */}
          <div className="bg-slate-800/50 rounded-xl p-4">
            <p className="text-white text-sm font-medium mb-2">Step 1 — Open your bot</p>
            <a href="https://t.me/Solarwatchpro_bot" target="_blank" rel="noreferrer"
               className="inline-flex items-center gap-2 px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium transition-colors">
              <Send className="w-4 h-4" /> Open @Solarwatchpro_bot → Send /start
            </a>
          </div>

          {/* Step 2 - Detect */}
          <div className="bg-slate-800/50 rounded-xl p-4">
            <p className="text-white text-sm font-medium mb-2">Step 2 — Detect your Chat ID</p>
            <div className="flex items-center gap-3">
              <button onClick={detectChatId} disabled={detectStatus === "loading"}
                className="px-4 py-2 rounded-lg bg-slate-700 hover:bg-slate-600 text-white text-sm font-medium transition-colors disabled:opacity-50">
                Auto-Detect Chat ID
              </button>
              <StatusBadge s={detectStatus} msg={detectMsg} />
            </div>
            {chatId && (
              <div className="mt-3 flex items-center gap-2 px-3 py-2 bg-emerald-500/10 border border-emerald-500/20 rounded-lg">
                <CheckCircle className="w-4 h-4 text-emerald-400" />
                <span className="text-emerald-400 text-sm font-mono">Chat ID: {chatId}</span>
                <span className="text-slate-400 text-xs ml-auto">Add TELEGRAM_CHAT_ID={chatId} to your .env</span>
              </div>
            )}
          </div>

          {/* Step 3 - Test */}
          <div className="bg-slate-800/50 rounded-xl p-4">
            <p className="text-white text-sm font-medium mb-2">Step 3 — Send a test message</p>
            <div className="flex items-center gap-3">
              <button onClick={sendTest} disabled={testStatus === "loading"}
                className="px-4 py-2 rounded-lg bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium transition-colors disabled:opacity-50 flex items-center gap-2">
                <Bell className="w-4 h-4" /> Send Test Alert
              </button>
              <StatusBadge s={testStatus} msg={testMsg} />
            </div>
          </div>
        </div>
      </div>

      {/* Alert Rules */}
      <div className="bg-slate-900/60 border border-slate-800 rounded-2xl p-6">
        <h2 className="font-semibold text-white mb-4">Alert Rules</h2>
        <div className="space-y-3">
          {ALERT_TYPES.map((a) => (
            <div key={a.title} className="flex items-start gap-4 p-3 rounded-xl hover:bg-slate-800/50 transition-colors">
              <span className="text-2xl mt-0.5">{a.icon}</span>
              <div className="flex-1">
                <p className="text-white text-sm font-medium">{a.title}</p>
                <p className="text-slate-400 text-xs mt-0.5">{a.desc}</p>
              </div>
              <div className={`mt-1 w-10 h-5 rounded-full flex items-center px-1 transition-colors ${a.active ? "bg-emerald-500 justify-end" : "bg-slate-700 justify-start"}`}>
                <div className="w-3.5 h-3.5 rounded-full bg-white shadow" />
              </div>
            </div>
          ))}
        </div>
        <p className="text-slate-500 text-xs mt-4 text-center">Alert rule editing coming in v1.1</p>
      </div>
    </div>
  );
}
