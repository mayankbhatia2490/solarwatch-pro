"use client";

import { useEffect, useState, useCallback } from "react";
import { ChevronLeft, ChevronRight, X, Loader2 } from "lucide-react";

interface DayData {
  date: string;
  precipitation_mm: number | null;
  kind: "rain_wash" | "light_rain" | "soiling_risk" | "dry";
  manual_clean?: boolean;
  clean_notes?: string;
  clean_type?: "manual" | "rain";
}

interface LogModalProps {
  date: string;
  onClose: () => void;
  onSaved: () => void;
}

function LogModal({ date, onClose, onSaved }: LogModalProps) {
  const [notes, setNotes] = useState("");
  const [type, setType] = useState<"manual" | "rain">("manual");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function submit() {
    setSaving(true);
    setError("");
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL ?? ""}/api/cleaning`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ date, notes, type }),
      });
      if (!res.ok) throw new Error(await res.text());
      onSaved();
      onClose();
    } catch (e: any) {
      setError(e.message || "Failed to save");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <div
        className="themed-card w-full max-w-sm mx-4 p-5 relative"
        onClick={e => e.stopPropagation()}
      >
        <button onClick={onClose} className="absolute top-3 right-3 text-[var(--text-muted)] hover:text-[var(--text-primary)]">
          <X className="w-4 h-4" />
        </button>
        <h3 className="font-bold text-base mb-1" style={{ color: "var(--card-value)" }}>
          Log Cleaning — {date}
        </h3>
        <p className="text-xs mb-4" style={{ color: "var(--text-secondary)" }}>
          Record that the panels were cleaned on this date.
        </p>

        <div className="space-y-3">
          <div>
            <label className="text-xs font-medium block mb-1" style={{ color: "var(--card-label)" }}>
              Type
            </label>
            <div className="flex gap-2">
              {(["manual", "rain"] as const).map(t => (
                <button
                  key={t}
                  onClick={() => setType(t)}
                  className={`flex-1 py-2 rounded-lg text-sm font-medium border transition-colors ${
                    type === t
                      ? "bg-emerald-500/20 border-emerald-500/50 text-emerald-500"
                      : "border-[var(--bg-border)] text-[var(--text-secondary)] hover:text-[var(--text-primary)]"
                  }`}
                >
                  {t === "manual" ? "🧹 Manual" : "🌧️ Rain"}
                </button>
              ))}
            </div>
          </div>

          <div>
            <label className="text-xs font-medium block mb-1" style={{ color: "var(--card-label)" }}>
              Notes (optional)
            </label>
            <textarea
              rows={2}
              value={notes}
              onChange={e => setNotes(e.target.value)}
              placeholder="e.g. Full wash with water + brush, time 8am"
              className="w-full rounded-lg px-3 py-2 text-sm resize-none border outline-none focus:border-emerald-500"
              style={{
                background: "var(--bg-surface)",
                color: "var(--card-value)",
                borderColor: "var(--bg-border)",
              }}
            />
          </div>

          {error && <p className="text-xs text-red-400">{error}</p>}

          <button
            onClick={submit}
            disabled={saving}
            className="w-full py-2.5 rounded-lg bg-emerald-500 hover:bg-emerald-600 text-white text-sm font-semibold transition-colors disabled:opacity-60 flex items-center justify-center gap-2"
          >
            {saving && <Loader2 className="w-4 h-4 animate-spin" />}
            {saving ? "Saving…" : "Save Cleaning"}
          </button>
        </div>
      </div>
    </div>
  );
}

function kindIcon(day: DayData): string {
  if (day.manual_clean) return day.clean_type === "rain" ? "🌧️" : "🧹";
  if (day.kind === "rain_wash")    return "🌧️";
  if (day.kind === "light_rain")   return "🌦️";
  if (day.kind === "soiling_risk") return "⚠️";
  return "";
}

function kindDotClass(day: DayData): string {
  if (day.manual_clean)            return "bg-violet-500";
  if (day.kind === "rain_wash")    return "bg-blue-400";
  if (day.kind === "light_rain")   return "bg-sky-300";
  if (day.kind === "soiling_risk") return "bg-amber-400";
  return "";
}

const MONTH_NAMES = [
  "January","February","March","April","May","June",
  "July","August","September","October","November","December",
];
const DOW = ["Su","Mo","Tu","We","Th","Fr","Sa"];

export function CleaningCalendar() {
  const today = new Date();
  const [year, setYear]   = useState(today.getFullYear());
  const [month, setMonth] = useState(today.getMonth()); // 0-indexed
  const [dayMap, setDayMap] = useState<Record<string, DayData>>({});
  const [loadError, setLoadError] = useState(false);
  const [modalDate, setModalDate] = useState<string | null>(null);

  const load = useCallback(async () => {
    try {
      const res = await fetch(`${process.env.NEXT_PUBLIC_API_URL ?? ""}/api/cleaning/rain-history?days=92`);
      if (!res.ok) throw new Error();
      const json = await res.json();
      const map: Record<string, DayData> = {};
      for (const d of json.days_data ?? []) map[d.date] = d;
      setDayMap(map);
      setLoadError(false);
    } catch {
      setLoadError(true);
    }
  }, []);

  useEffect(() => { load(); }, [load]);

  // Build calendar grid for current month
  const firstDay = new Date(year, month, 1).getDay(); // 0=Sun
  const daysInMonth = new Date(year, month + 1, 0).getDate();

  const cells: (number | null)[] = [
    ...Array(firstDay).fill(null),
    ...Array.from({ length: daysInMonth }, (_, i) => i + 1),
  ];
  // Pad to complete last row
  while (cells.length % 7 !== 0) cells.push(null);

  function prevMonth() {
    if (month === 0) { setYear(y => y - 1); setMonth(11); }
    else setMonth(m => m - 1);
  }
  function nextMonth() {
    const now = new Date();
    if (year > now.getFullYear() || (year === now.getFullYear() && month >= now.getMonth())) return;
    if (month === 11) { setYear(y => y + 1); setMonth(0); }
    else setMonth(m => m + 1);
  }

  function isoDate(d: number) {
    return `${year}-${String(month + 1).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
  }

  function isToday(d: number) {
    return d === today.getDate() && month === today.getMonth() && year === today.getFullYear();
  }

  function isFuture(d: number) {
    const dt = new Date(year, month, d);
    const todayStart = new Date(today.getFullYear(), today.getMonth(), today.getDate());
    return dt > todayStart;
  }

  const atMaxMonth = year === today.getFullYear() && month >= today.getMonth();

  // Stats for visible month
  const monthPrefix = `${year}-${String(month + 1).padStart(2, "0")}`;
  const monthDays = Object.values(dayMap).filter(d => d.date.startsWith(monthPrefix));
  const stats = {
    cleans:  monthDays.filter(d => d.manual_clean).length,
    rain:    monthDays.filter(d => d.kind === "rain_wash" && !d.manual_clean).length,
    soiling: monthDays.filter(d => d.kind === "soiling_risk").length,
  };

  return (
    <div className="themed-card p-5">
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div>
          <h2 className="text-base font-bold" style={{ color: "var(--card-value)" }}>
            Cleaning Calendar
          </h2>
          <p className="text-xs mt-0.5" style={{ color: "var(--text-secondary)" }}>
            Click any past date to log a cleaning
          </p>
        </div>
        <div className="flex items-center gap-1">
          <button onClick={prevMonth} className="p-1.5 rounded-lg hover:bg-[var(--bg-hover)] text-[var(--text-secondary)]">
            <ChevronLeft className="w-4 h-4" />
          </button>
          <span className="text-sm font-semibold px-2 min-w-[120px] text-center" style={{ color: "var(--card-value)" }}>
            {MONTH_NAMES[month]} {year}
          </span>
          <button onClick={nextMonth} disabled={atMaxMonth}
            className="p-1.5 rounded-lg hover:bg-[var(--bg-hover)] text-[var(--text-secondary)] disabled:opacity-30">
            <ChevronRight className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Legend */}
      <div className="flex flex-wrap gap-3 mb-3 text-xs" style={{ color: "var(--text-secondary)" }}>
        <span className="flex items-center gap-1"><span>🧹</span> Manual clean</span>
        <span className="flex items-center gap-1"><span>🌧️</span> Rain wash (&gt;10mm)</span>
        <span className="flex items-center gap-1"><span>🌦️</span> Light rain (2-10mm)</span>
        <span className="flex items-center gap-1"><span>⚠️</span> Soiling risk</span>
      </div>

      {/* Day-of-week header */}
      <div className="grid grid-cols-7 mb-1">
        {DOW.map(d => (
          <div key={d} className="text-center text-xs font-medium py-1" style={{ color: "var(--text-muted)" }}>{d}</div>
        ))}
      </div>

      {/* Calendar grid */}
      <div className="grid grid-cols-7 gap-0.5">
        {cells.map((day, idx) => {
          if (!day) return <div key={idx} />;
          const iso = isoDate(day);
          const data = dayMap[iso];
          const future = isFuture(day);
          const dot = data ? kindDotClass(data) : "";
          const icon = data ? kindIcon(data) : "";

          return (
            <button
              key={idx}
              disabled={future}
              onClick={() => !future && setModalDate(iso)}
              title={
                data?.manual_clean
                  ? `Cleaned${data.clean_notes ? ": " + data.clean_notes : ""}`
                  : data?.kind === "rain_wash" ? `Rain wash — ${data.precipitation_mm}mm`
                  : data?.kind === "light_rain" ? `Light rain — ${data.precipitation_mm}mm`
                  : data?.kind === "soiling_risk" ? "Possible soiling after light rain"
                  : "Click to log cleaning"
              }
              className={`
                relative flex flex-col items-center justify-center rounded-lg py-1.5 text-xs font-medium
                transition-colors min-h-[44px]
                ${future ? "opacity-30 cursor-default" : "hover:bg-[var(--bg-hover)] cursor-pointer"}
                ${isToday(day) ? "ring-1 ring-emerald-500" : ""}
                ${data?.manual_clean ? "bg-violet-500/10" : ""}
              `}
              style={{ color: isToday(day) ? "var(--card-value)" : "var(--text-secondary)" }}
            >
              <span className={isToday(day) ? "font-bold text-emerald-500" : ""}>{day}</span>
              {icon && <span className="text-xs leading-none mt-0.5">{icon}</span>}
              {dot && !icon && <span className={`w-1.5 h-1.5 rounded-full mt-0.5 ${dot}`} />}
            </button>
          );
        })}
      </div>

      {/* Month summary */}
      {(stats.cleans > 0 || stats.rain > 0 || stats.soiling > 0) && (
        <div className="mt-3 pt-3 border-t flex gap-4 text-xs" style={{ borderColor: "var(--bg-border)", color: "var(--text-secondary)" }}>
          {stats.cleans  > 0 && <span>🧹 {stats.cleans} clean{stats.cleans > 1 ? "s" : ""}</span>}
          {stats.rain    > 0 && <span>🌧️ {stats.rain} rain wash{stats.rain > 1 ? "es" : ""}</span>}
          {stats.soiling > 0 && <span>⚠️ {stats.soiling} soiling risk day{stats.soiling > 1 ? "s" : ""}</span>}
        </div>
      )}

      {loadError && (
        <p className="mt-2 text-xs text-amber-400">Could not load rain data — check API connection.</p>
      )}

      {modalDate && (
        <LogModal
          date={modalDate}
          onClose={() => setModalDate(null)}
          onSaved={load}
        />
      )}
    </div>
  );
}
