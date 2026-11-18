"use client";
import dynamic from "next/dynamic";
import type { EChartsOption } from "echarts";
import { useEffect, useState } from "react";
const ReactECharts = dynamic(() => import("echarts-for-react"), { ssr: false });

export function colors() {
  const read = (name: string, fallback: string) => typeof window === "undefined" ? fallback :
    getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
  return { http: read("--chart-http", "#0891B2"), l7: read("--chart-l7", "#EF4444"),
    bot: read("--chart-bot", "#F59E0B"), human: read("--chart-human", "#10B981"),
    trend: read("--chart-trend", "#64748B"), netflow: read("--chart-netflow", "#6366F1"),
    grid: read("--chart-grid", "#E2E8F0"), axis: read("--chart-axis", "#7A8AA0"),
    neg: read("--heat-neg-2", "#B91C1C"), pos: read("--heat-pos-2", "#0E7490") };
}
export function chartBase(options: EChartsOption, zoom = false): EChartsOption {
  const c = colors();
  return { animationDuration: 1700, animationEasing: "cubicOut", animationDurationUpdate: 1100, animationEasingUpdate: "cubicInOut",
    grid: { left: 48, top: 38, right: 22, bottom: zoom ? 57 : 37, containLabel: false },
    tooltip: { trigger: "axis", backgroundColor: "#0B1F3A", borderWidth: 0, textStyle: { color: "#fff", fontSize: 12 } },
    xAxis: { type: "category", axisLine: { lineStyle: { color: c.grid } }, axisLabel: { color: c.axis, fontSize: 10 }, axisTick: { show: false } },
    yAxis: { type: "value", axisLabel: { color: c.axis, fontSize: 10 }, splitLine: { lineStyle: { color: c.grid } } },
    ...(zoom ? { dataZoom: [{ type: "inside" as const }, { type: "slider" as const, height: 17, bottom: 9, borderColor: c.grid, textStyle: { color: c.axis } }] } : {}),
    ...options };
}
type RevealSeries = { type?: string; data?: unknown[] };

function numericValue(value: unknown, axis: "x" | "y", type?: string): number | null {
  if (typeof value === "number") return axis === "y" ? value : null;
  if (Array.isArray(value)) {
    const index = axis === "x" ? 0 : type === "heatmap" ? 2 : 1;
    return typeof value[index] === "number" ? value[index] : null;
  }
  if (value && typeof value === "object" && "value" in value) return numericValue(value.value, axis, type);
  return null;
}

function niceMax(value: number): number {
  const step = 10 ** (Math.floor(Math.log10(value)) - 1);
  return Number((Math.ceil(value * 1.02 / step) * step).toPrecision(12));
}

function stableAxis(axis: EChartsOption["xAxis"] | EChartsOption["yAxis"], series: RevealSeries[], direction: "x" | "y") {
  if (!axis || Array.isArray(axis) || axis.type !== "value" || axis.max != null) return axis;
  const values = series.flatMap(item => (item.data ?? []).map(value => numericValue(value, direction, item.type)));
  const maximum = Math.max(0, ...values.filter((value): value is number => value != null && Number.isFinite(value)));
  return maximum > 0 ? { ...axis, max: niceMax(maximum) } : axis;
}

function orderedData(series: RevealSeries): unknown[] {
  const data = series.data ?? [];
  if (series.type === "scatter" || series.type === "heatmap") {
    return [...data].sort((a, b) => (numericValue(a, "x", series.type) ?? 0) - (numericValue(b, "x", series.type) ?? 0));
  }
  return data;
}

function revealData(series: RevealSeries, shown: number, total: number): unknown[] {
  const data = orderedData(series);
  return data.slice(0, series.type === "scatter" || series.type === "heatmap" ? Math.max(1, Math.ceil(data.length * shown / total)) : shown);
}

export default function DataChart({ option, className = "chart", onEvents }: { option: EChartsOption; className?: string; onEvents?: Record<string, (params: { dataIndex?: number }) => void> }) {
  const series = (Array.isArray(option.series) ? option.series : option.series ? [option.series] : []) as RevealSeries[];
  const total = Math.max(0, ...series.map(item => item.data?.length ?? 0));
  const [ready, setReady] = useState(false);
  const [shown, setShown] = useState(1);
  const [finished, setFinished] = useState(false);
  const duration = Math.min(7_500, Math.max(1_800, (total - 1) * 250));
  const stepDuration = duration / Math.max(1, total - 1);

  useEffect(() => {
    if (!ready || total < 2) return;
    let count = 1;
    const timer = window.setInterval(() => {
      count += 1;
      setShown(count);
      if (count >= total) {
        window.clearInterval(timer);
        finishTimer = window.setTimeout(() => setFinished(true), Math.min(260, stepDuration * .85));
      }
    }, stepDuration);
    let finishTimer = 0;
    return () => { window.clearInterval(timer); window.clearTimeout(finishTimer); };
  }, [ready, total, stepDuration]);

  const normalized: EChartsOption = {
    ...option,
    xAxis: stableAxis(option.xAxis, series, "x") as EChartsOption["xAxis"],
    yAxis: stableAxis(option.yAxis, series, "y") as EChartsOption["yAxis"],
    series: series.map(item => ({ ...item, data: orderedData(item) })) as EChartsOption["series"],
  };
  const displayOption: EChartsOption = finished ? normalized : {
    ...normalized,
    animationDuration: 0,
    animationDurationUpdate: Math.min(260, stepDuration * .85),
    animationEasingUpdate: "linear",
    series: series.map(item => ({ ...item, data: revealData(item, shown, Math.max(1, total)) })) as EChartsOption["series"],
  };
  return <div className={className}>
    <ReactECharts option={{ ...displayOption, animation: true }} onEvents={onEvents} onChartReady={() => setReady(true)}
      lazyUpdate={false} style={{ width: "100%", height: "100%" }} />
  </div>;
}
