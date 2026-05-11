"use client";
import dynamic from "next/dynamic";

const ApexChart = dynamic(() => import("react-apexcharts"), { ssr: false });

interface GenerationChartProps {
  data: { time: string; power_w: number; expected_w: number }[];
}

export function GenerationChart({ data }: GenerationChartProps) {
  const times = data.map(d => new Date(d.time).getTime());
  const actual = data.map(d => d.power_w);
  const expected = data.map(d => d.expected_w);

  const options: ApexCharts.ApexOptions = {
    chart: {
      type: "area",
      background: "transparent",
      toolbar: { show: false },
      zoom: { enabled: true },
      animations: { enabled: true, speed: 800 },
    },
    theme: { mode: "dark" },
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
      categories: times,
      labels: { style: { colors: "#64748b" }, datetimeUTC: false },
      axisBorder: { show: false },
      axisTicks: { show: false },
    },
    yaxis: {
      labels: {
        style: { colors: "#64748b" },
        formatter: (v) => `${(v / 1000).toFixed(1)}kW`,
      },
    },
    grid: { borderColor: "#1e293b", strokeDashArray: 4 },
    legend: {
      labels: { colors: "#94a3b8" },
      position: "top",
      horizontalAlign: "right",
    },
    tooltip: {
      theme: "dark",
      x: { format: "HH:mm dd MMM" },
      y: { formatter: (v) => `${v.toFixed(0)} W` },
    },
  };

  const series = [
    { name: "Actual Output", data: actual },
    { name: "Expected (Weather Adjusted)", data: expected },
  ];

  if (!data.length) {
    return (
      <div className="flex items-center justify-center h-64 text-slate-500 text-sm">
        No data for selected range
      </div>
    );
  }

  return <ApexChart type="area" options={options} series={series} height={260} />;
}
