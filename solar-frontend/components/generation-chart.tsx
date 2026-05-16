"use client";
import dynamic from "next/dynamic";
import { useTheme } from "next-themes";

const ApexChart = dynamic(() => import("react-apexcharts"), { ssr: false });

interface GenerationChartProps {
  data: { time: string; power_w: number; expected_w: number }[];
  isNight?: boolean;
  sunrise?: string;
}

export function GenerationChart({ data, isNight, sunrise }: GenerationChartProps) {
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === "dark";

  const times = data.map(d => new Date(d.time).getTime());
  const actual = data.map((d, i) => [times[i], d.power_w] as [number, number]);
  const expected = data.map((d, i) => [times[i], d.expected_w] as [number, number]);

  const labelColor  = isDark ? "#64748b" : "#94a3b8";
  const gridColor   = isDark ? "#1e293b" : "#e2e8f0";
  const legendColor = isDark ? "#94a3b8" : "#475569";

  const options: ApexCharts.ApexOptions = {
    chart: {
      type: "area",
      background: "transparent",
      toolbar: { show: false },
      zoom: { enabled: true },
      animations: { enabled: true, speed: 800 },
    },
    theme: { mode: isDark ? "dark" : "light" },
    colors: ["#22c55e", "#3b82f6"],
    stroke: { curve: "smooth", width: [2, 1.5] },
    fill: {
      type: ["gradient", "solid"],
      gradient: {
        shadeIntensity: 1, opacityFrom: 0.4, opacityTo: 0.05, stops: [0, 100],
      },
      opacity: [1, 0],
    },
    dataLabels: { enabled: false },
    xaxis: {
      type: "datetime",
      labels: { style: { colors: labelColor }, datetimeUTC: false },
      axisBorder: { show: false },
      axisTicks: { show: false },
    },
    yaxis: {
      labels: {
        style: { colors: labelColor },
        formatter: (v) => `${(v / 1000).toFixed(1)}kW`,
      },
    },
    grid: { borderColor: gridColor, strokeDashArray: 4 },
    legend: {
      labels: { colors: legendColor },
      position: "top",
      horizontalAlign: "right",
    },
    tooltip: {
      theme: isDark ? "dark" : "light",
      x: { format: "HH:mm dd MMM" },
      y: { formatter: (v) => `${v.toFixed(0)} W` },
    },
  };

  const series = [
    { name: "Actual Output", data: actual },
    { name: "Expected (Weather Adjusted)", data: expected },
  ];

  if (!data.length) {
    const sunriseStr = sunrise
      ? new Date(sunrise).toLocaleTimeString("en-IN", { hour: "2-digit", minute: "2-digit" })
      : "~6:00 AM";
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-2 select-none">
        {isNight ? (
          <>
            <span className="text-3xl">🌙</span>
            <span className="text-sm font-medium" style={{ color: "var(--card-value)" }}>System resting overnight</span>
            <span className="text-xs" style={{ color: "var(--card-sub)" }}>Generation resumes at sunrise · {sunriseStr}</span>
          </>
        ) : (
          <span className="text-sm" style={{ color: "var(--card-sub)" }}>No data for selected range</span>
        )}
      </div>
    );
  }

  return <ApexChart type="area" options={options} series={series} height={260} />;
}
