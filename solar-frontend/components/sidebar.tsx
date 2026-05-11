"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { Sun, Zap, GitBranch, AlertTriangle, Grid, Thermometer, Wrench, TrendingUp, Cloud, FileText, Bell, Settings, Menu, X, Moon } from "lucide-react";
import { useState } from "react";
import { useTheme } from "next-themes";

const nav = [
  { href: "/", label: "Dashboard", icon: Sun },
  { href: "/electrical", label: "Electrical", icon: Zap },
  { href: "/strings", label: "String Compare", icon: GitBranch },
  { href: "/anomalies", label: "Anomalies", icon: AlertTriangle },
  { href: "/grid", label: "Grid Quality", icon: Grid },
  { href: "/thermal", label: "Thermal", icon: Thermometer },
  { href: "/maintenance", label: "Maintenance", icon: Wrench },
  { href: "/performance", label: "Performance", icon: TrendingUp },
  { href: "/weather", label: "Weather Context", icon: Cloud },
  { href: "/reports", label: "Reports", icon: FileText },
  { href: "/alerts", label: "Alert Config", icon: Bell },
  { href: "/settings", label: "Settings", icon: Settings },
];

export function Sidebar() {
  const path = usePathname();
  const [open, setOpen] = useState(false);
  const { theme, setTheme } = useTheme();

  return (
    <>
      {/* Mobile top bar */}
      <div className="fixed top-0 left-0 right-0 z-50 flex items-center justify-between px-4 py-3 bg-[var(--sidebar-bg)]/90 backdrop-blur-sm border-b border-[var(--sidebar-border)] lg:hidden">
        <div className="flex items-center gap-2">
          <div className="w-7 h-7 rounded-lg bg-gradient-to-br from-emerald-400 to-green-600 flex items-center justify-center">
            <Sun className="w-4 h-4 text-white" />
          </div>
          <span className="font-bold text-[var(--text-primary)] text-sm">SolarWatch Pro</span>
        </div>
        <div className="flex items-center gap-2">
          {/* Theme toggle — mobile */}
          <button
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            className="p-1.5 rounded-lg text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] transition-colors"
            title="Toggle theme"
          >
            {theme === "dark" ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
          </button>
          <button onClick={() => setOpen(!open)} className="p-1.5 rounded-lg text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] transition-colors">
            {open ? <X className="w-5 h-5" /> : <Menu className="w-5 h-5" />}
          </button>
        </div>
      </div>

      {/* Mobile overlay */}
      {open && <div className="fixed inset-0 z-40 bg-black/60 lg:hidden" onClick={() => setOpen(false)} />}

      {/* Sidebar */}
      <aside className={`fixed top-0 left-0 z-40 h-full w-64 bg-[var(--sidebar-bg)] border-r border-[var(--sidebar-border)] flex flex-col transition-transform duration-300 ${open ? "translate-x-0" : "-translate-x-full"} lg:translate-x-0`}>
        {/* Logo + theme toggle */}
        <div className="flex items-center justify-between px-5 py-6 border-b border-[var(--sidebar-border)]">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-emerald-400 to-green-600 flex items-center justify-center shadow-lg shadow-emerald-900/40">
              <Sun className="w-5 h-5 text-white" />
            </div>
            <div>
              <div className="font-bold text-[var(--text-primary)] text-sm">SolarWatch Pro</div>
              <div className="text-xs text-[var(--text-secondary)]">Solar Monitoring</div>
            </div>
          </div>
          {/* Theme toggle — desktop sidebar */}
          <button
            onClick={() => setTheme(theme === "dark" ? "light" : "dark")}
            className="p-2 rounded-xl bg-[var(--bg-hover)] border border-[var(--bg-border)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] transition-colors"
            title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
          >
            {theme === "dark" ? <Sun className="w-4 h-4" /> : <Moon className="w-4 h-4" />}
          </button>
        </div>

        {/* Live indicator */}
        <div className="mx-4 mt-4 mb-2 px-3 py-2 rounded-xl bg-emerald-500/10 border border-emerald-500/20 flex items-center gap-2">
          <span className="pulse-green w-2 h-2 rounded-full bg-emerald-400 inline-block" />
          <span className="text-xs text-emerald-400 font-medium">Live Monitoring Active</span>
        </div>

        {/* Nav */}
        <nav className="flex-1 px-3 py-4 space-y-1 overflow-y-auto">
          {nav.map(({ href, label, icon: Icon }) => {
            const active = path === href;
            return (
              <Link key={href} href={href} onClick={() => setOpen(false)}
                className={`flex items-center gap-3 px-3 py-2.5 rounded-xl text-sm font-medium transition-all duration-200 ${
                  active
                    ? "bg-[var(--sidebar-active)] text-emerald-500 border border-emerald-500/25"
                    : "text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)]"
                }`}>
                <Icon className={`w-4 h-4 flex-shrink-0 ${active ? "text-emerald-500" : ""}`} />
                {label}
                {active && <span className="ml-auto w-1.5 h-1.5 rounded-full bg-emerald-400" />}
              </Link>
            );
          })}
        </nav>

        {/* Footer */}
        <div className="px-5 py-4 border-t border-[var(--sidebar-border)]">
          <div className="text-xs text-[var(--text-secondary)]">Version 1.0 MVP</div>
          <div className="text-xs text-[var(--text-muted)] mt-0.5">Data refreshes every 5 min</div>
        </div>
      </aside>

      {/* Mobile bottom padding */}
      <div className="h-16 lg:hidden" />
    </>
  );
}
