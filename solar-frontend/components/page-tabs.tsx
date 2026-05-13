"use client";

import { ReactNode } from "react";

export interface TabDef {
  id: string;
  label: string;
  icon?: string;  // emoji or short text badge
}

interface PageTabsProps {
  tabs: TabDef[];
  active: string;
  onChange: (id: string) => void;
  className?: string;
}

export function PageTabs({ tabs, active, onChange, className = "" }: PageTabsProps) {
  return (
    <div className={`flex gap-1 p-1 rounded-xl ${className}`}
         style={{ background: "var(--bg-surface-2)", border: "1px solid var(--bg-border)" }}>
      {tabs.map(t => (
        <button
          key={t.id}
          onClick={() => onChange(t.id)}
          className={`flex items-center gap-1.5 px-4 py-2 rounded-lg text-sm font-medium transition-all duration-150 ${
            active === t.id
              ? "bg-emerald-500 text-white shadow-sm"
              : "text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)]"
          }`}
        >
          {t.icon && <span>{t.icon}</span>}
          {t.label}
        </button>
      ))}
    </div>
  );
}

interface TabPanelProps {
  id: string;
  active: string;
  children: ReactNode;
}

/** Renders children only when the tab is active — lazy-loading pattern */
export function TabPanel({ id, active, children }: TabPanelProps) {
  if (id !== active) return null;
  return <>{children}</>;
}
