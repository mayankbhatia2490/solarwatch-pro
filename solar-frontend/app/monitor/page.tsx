"use client";

import { useState } from "react";
import { PageTabs, TabPanel } from "@/components/page-tabs";
import ElectricalPage from "@/app/electrical/page";
import GridPage      from "@/app/grid/page";
import ThermalPage   from "@/app/thermal/page";
import AnomaliesPage from "@/app/anomalies/page";

const TABS = [
  { id: "electrical", label: "Electrical",    icon: "⚡" },
  { id: "grid",       label: "Grid Quality",  icon: "🔌" },
  { id: "thermal",    label: "Thermal",       icon: "🌡️" },
  { id: "anomalies",  label: "Anomalies",     icon: "⚠️" },
];

export default function MonitorPage() {
  const [active, setActive] = useState("electrical");

  return (
    <div className="space-y-5 max-w-7xl">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold" style={{ color: "var(--card-value)" }}>Live Monitor</h1>
          <p className="text-sm mt-0.5" style={{ color: "var(--card-sub)" }}>
            Real-time electrical, grid, thermal and anomaly data · KSY 3.4kW-1Ph
          </p>
        </div>
        <PageTabs tabs={TABS} active={active} onChange={setActive} />
      </div>

      <TabPanel id="electrical" active={active}><ElectricalPage /></TabPanel>
      <TabPanel id="grid"       active={active}><GridPage /></TabPanel>
      <TabPanel id="thermal"    active={active}><ThermalPage /></TabPanel>
      <TabPanel id="anomalies"  active={active}><AnomaliesPage /></TabPanel>
    </div>
  );
}
