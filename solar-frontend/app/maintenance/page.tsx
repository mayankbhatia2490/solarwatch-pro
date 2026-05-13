"use client";

import { useState } from "react";
import { PageTabs, TabPanel } from "@/components/page-tabs";
import ReportsPage from "@/app/reports/page";
import MaintenanceContent from "./maintenance-content";

const TABS = [
  { id: "maintenance", label: "Cleaning & Service", icon: "🔧" },
  { id: "reports",     label: "Reports & Export",   icon: "📄" },
];

export default function MaintenancePage() {
  const [active, setActive] = useState("maintenance");

  return (
    <div className="space-y-5 max-w-6xl">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold" style={{ color: "var(--card-value)" }}>Maintenance</h1>
          <p className="text-sm mt-0.5" style={{ color: "var(--card-sub)" }}>
            Cleaning calendar · service predictions · reports & data export
          </p>
        </div>
        <PageTabs tabs={TABS} active={active} onChange={setActive} />
      </div>

      <TabPanel id="maintenance" active={active}><MaintenanceContent /></TabPanel>
      <TabPanel id="reports"     active={active}><ReportsPage /></TabPanel>
    </div>
  );
}
