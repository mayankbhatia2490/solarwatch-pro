const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "";

async function get(path: string) {
  const res = await fetch(`${API_BASE}${path}`, { cache: "no-store" });
  if (!res.ok) throw new Error(`${path} → ${res.status}`);
  return res.json();
}

export function fetchDashboardSummary() {
  return get("/api/dashboard/summary");
}

export function fetchDailyChart(
  range: string,
  from?: string,
  to?: string,
) {
  const params = new URLSearchParams({ range });
  if (from) params.set("from", from);
  if (to)   params.set("to", to);
  return get(`/api/dashboard/daily-chart?${params}`);
}

export function fetchHealthScorecard() {
  return get("/api/dashboard/health-scorecard");
}
