"use client";

import HistoricalTab from "@/app/performance/historical-tab";

export default function LongTermPage() {
  return (
    <div className="space-y-5 max-w-6xl">
      <div>
        <h1 className="text-2xl font-bold" style={{ color: "var(--card-value)" }}>Long-term Performance</h1>
        <p className="text-sm mt-0.5" style={{ color: "var(--card-sub)" }}>
          Year-over-year · panel degradation · system specs · best days
        </p>
      </div>
      <HistoricalTab />
    </div>
  );
}
