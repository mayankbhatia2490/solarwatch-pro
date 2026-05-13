"use client";

import { useState } from "react";
import { PageTabs, TabPanel } from "@/components/page-tabs";
import AnalysisPage from "@/app/analysis/page";
import WeatherPage  from "@/app/weather/page";
import HistoricalTab from "./historical-tab";

const TABS = [
  { id: "analysis",   label: "Performance Analysis", icon: "📊" },
  { id: "weather",    label: "Weather",              icon: "🌤️" },
  { id: "historical", label: "Long-term",            icon: "📅" },
];

export default function PerformanceHubPage() {
  const [active, setActive] = useState("analysis");

  return (
    <div className="space-y-5 max-w-7xl">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold" style={{ color: "var(--card-value)" }}>Performance Hub</h1>
          <p className="text-sm mt-0.5" style={{ color: "var(--card-sub)" }}>
            Weather-adjusted analysis · AI diagnostics · long-term trends · KSY 3.4kW-1Ph
          </p>
        </div>
        <PageTabs tabs={TABS} active={active} onChange={setActive} />
      </div>

      <TabPanel id="analysis"   active={active}><AnalysisPage /></TabPanel>
      <TabPanel id="weather"    active={active}><WeatherPage /></TabPanel>
      <TabPanel id="historical" active={active}><HistoricalTab /></TabPanel>
    </div>
  );
}
