"use client";
import { useState } from "react";
import type { Metric } from "@/types/api";
import { DATA_MODE } from "@/lib/api";

export const metricLabels: Record<Metric, string> = {
  http_traffic: "Lưu lượng HTTP", l7_attack: "Tấn công L7", bot_share: "Tỷ lệ bot",
  human_share: "Tỷ lệ người dùng", netflows: "Lưu lượng mạng",
};
export const metricUnit = (metric: Metric) => metric.endsWith("share") ? "%" : "chỉ số";
export type Granularity = "day" | "week" | "month";
export type Filters = { start: string; end: string; metric: Metric; granularity: Granularity };

function daysAgo(days: number, end: string) {
  const date = new Date(`${end}T00:00:00Z`); date.setUTCDate(date.getUTCDate() - days);
  return date.toISOString().slice(0, 10);
}
export function useDashboardFilters(defaultMetric: Metric = "http_traffic") {
  const [filters, setFilters] = useState<Filters>(() => {
    const end = DATA_MODE === "demo" ? "2026-11-17" : new Date().toISOString().slice(0, 10);
    return { start: daysAgo(30, end), end, metric: defaultMetric, granularity: "day" };
  });
  return { filters, setFilters, preset(days: number) { setFilters(f => ({ ...f, start: daysAgo(days, f.end) })); } };
}
export default function DashboardFilters({ filters, setFilters, showMetric = true }: {
  filters: Filters; setFilters: (next: Filters | ((old: Filters) => Filters)) => void; showMetric?: boolean;
}) {
  return <div className="filters" aria-label="Bộ lọc biểu đồ">
    <div className="filter filter-date"><label htmlFor="date-from">Từ ngày</label><input id="date-from" className="input" type="date" max={filters.end} value={filters.start} onChange={e => setFilters(f => ({ ...f, start: e.target.value }))}/></div>
    <div className="filter filter-date"><label htmlFor="date-to">Đến ngày</label><input id="date-to" className="input" type="date" min={filters.start} value={filters.end} onChange={e => setFilters(f => ({ ...f, end: e.target.value }))}/></div>
    {showMetric && <div className="filter filter-wide"><label htmlFor="metric">Chỉ số</label><select id="metric" className="input" value={filters.metric} onChange={e => setFilters(f => ({ ...f, metric: e.target.value as Metric }))}>
      {Object.entries(metricLabels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}
    </select></div>}
    <div className="filter"><label>Độ phân giải</label><div className="segmented" role="group" aria-label="Độ phân giải">
      {(["day", "week", "month"] as Granularity[]).map((item, i) => <button key={item} type="button" aria-pressed={filters.granularity === item} onClick={() => setFilters(f => ({ ...f, granularity: item }))}>{["Ngày", "Tuần", "Tháng"][i]}</button>)}
    </div></div>
  </div>;
}
