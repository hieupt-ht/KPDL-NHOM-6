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
    neg: read("--heat-neg-2", "#B91C1C"), negSoft: read("--heat-neg-1", "#FCA5A5"), zero: read("--heat-zero", "#F1F5F9"),
    posSoft: read("--heat-pos-1", "#67C8DD"), pos: read("--heat-pos-2", "#0E7490"),
    muted: read("--chart-muted", "#94A3B8"), text: read("--text-secondary", "#4A5B73"),
    tooltipBg: read("--tooltip-bg", "#0B1F3A"), tooltipBorder: read("--tooltip-border", "#1E3A5F"), surface: read("--bg-surface", "#FFFFFF") };
}
/** Gradient dọc mờ dần dưới đường line (areaStyle.color). */
export function areaGradient(color: string, top = .28) {
  const alpha = (a: number) => color.startsWith("#") && color.length === 7 ? color + Math.round(a * 255).toString(16).padStart(2, "0") : color;
  return { type: "linear" as const, x: 0, y: 0, x2: 0, y2: 1, colorStops: [{ offset: 0, color: alpha(top) }, { offset: 1, color: alpha(0) }] };
}
export function chartBase(options: EChartsOption, zoom = false): EChartsOption {
  const c = colors();
  const base: EChartsOption = { animationDuration: 1700, animationEasing: "cubicOut", animationDurationUpdate: 1100, animationEasingUpdate: "cubicInOut",
    textStyle: { fontFamily: "'Inter Variable', Inter, system-ui, sans-serif" },
    grid: { left: 48, top: 38, right: 22, bottom: zoom ? 60 : 37, containLabel: false },
    tooltip: { trigger: "axis", backgroundColor: c.tooltipBg, borderColor: c.tooltipBorder, borderWidth: 1, padding: [8, 12],
      extraCssText: "border-radius:10px;box-shadow:0 10px 30px rgba(2,8,23,.28);backdrop-filter:blur(6px)",
      textStyle: { color: "#fff", fontSize: 12 }, axisPointer: { type: "line", lineStyle: { color: c.axis, type: "dashed" } } },
    xAxis: { type: "category", axisLine: { lineStyle: { color: c.grid } }, axisLabel: { color: c.axis, fontSize: 10 }, axisTick: { show: false } },
    yAxis: { type: "value", axisLabel: { color: c.axis, fontSize: 10 }, nameTextStyle: { color: c.axis, fontSize: 10 }, splitLine: { lineStyle: { color: c.grid, type: [4, 4] } } },
    ...(zoom ? { dataZoom: [{ type: "inside" as const }, { type: "slider" as const, height: 18, bottom: 9, borderColor: "transparent", backgroundColor: c.grid + "55",
      fillerColor: c.http + "22", handleStyle: { color: c.surface, borderColor: c.http }, moveHandleStyle: { color: c.http }, dataBackground: { lineStyle: { color: c.axis, opacity: .5 }, areaStyle: { color: c.axis, opacity: .12 } },
      selectedDataBackground: { lineStyle: { color: c.http }, areaStyle: { color: c.http, opacity: .2 } }, textStyle: { color: c.axis, fontSize: 10 } }] } : {}),
    ...options };
  // Giữ style chung khi trang chỉ ghi đè một phần tooltip/legend.
  const tooltip = base.tooltip as Record<string, unknown>;
  const own = (options.tooltip && !Array.isArray(options.tooltip) ? options.tooltip : {}) as Record<string, unknown>;
  const legend = options.legend && !Array.isArray(options.legend) ? { icon: "roundRect", itemWidth: 12, itemHeight: 4, itemGap: 14,
    ...(options.legend as Record<string, unknown>), textStyle: { color: c.text, fontSize: 11 } } : options.legend;
  // Trục do trang truyền vào chỉ ghi đè thuộc tính riêng, vẫn giữ màu/lưới theo theme.
  const axis = (key: "xAxis" | "yAxis") => {
    const theirs = options[key];
    if (!theirs || Array.isArray(theirs)) return theirs ?? base[key];
    const page = theirs as Record<string, unknown>;
    const themed = page.type === "category" ? { axisLine: { lineStyle: { color: c.grid } }, axisTick: { show: false } } : { splitLine: { lineStyle: { color: c.grid, type: [4, 4] } } };
    return { ...themed, nameTextStyle: { color: c.axis, fontSize: 10 }, ...page, axisLabel: { color: c.axis, fontSize: 10, ...(page.axisLabel as object) } };
  };
  return { ...base, xAxis: axis("xAxis"), yAxis: axis("yAxis"), tooltip: { ...tooltip, ...own }, ...(legend ? { legend } : {}) } as EChartsOption;
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
