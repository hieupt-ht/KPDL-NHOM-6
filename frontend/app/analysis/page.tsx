"use client";
import { vietnamDay } from "@/lib/date-utils";
import { useState } from "react";
import useSWR from "swr";
import type { EChartsOption } from "echarts";
import DataChart, { chartBase, colors } from "@/components/charts/DataChart";
import DashboardFilters, { metricLabels, metricUnit, useDashboardFilters } from "@/components/filters/DashboardFilters";
import { DataState, PageHeading, Panel, SourceNote } from "@/components/ui/Elements";
import { DATA_MODE, DATA_REFRESH_INTERVAL, getClusters, getCorrelation, getHistogram, getSeasonal, getTimeseries, getTrend } from "@/lib/api";

const refreshInterval = DATA_REFRESH_INTERVAL;
const dateLabel = (s: string) => new Intl.DateTimeFormat("vi-VN", { day: "2-digit", month: "2-digit", timeZone: "Asia/Ho_Chi_Minh" }).format(new Date(s));

export default function AnalysisPage() {
  const { filters, setFilters } = useDashboardFilters();
  const [period, setPeriod] = useState<"hour_of_day" | "day_of_week" | "month">("hour_of_day");
  const range = { start: filters.start, end: filters.end };
  const q = { ...range, granularity: filters.granularity, metric: filters.metric };
  const time = useSWR(["analysis-time", q], () => getTimeseries(q), { refreshInterval });
  const scatterTraffic = useSWR(["scatter-http", range], () => getTimeseries({ ...range, granularity: "day", metric: "http_traffic" }), { refreshInterval });
  const bot = useSWR(["analysis-bot", range], () => getTimeseries({ ...range, granularity: "day", metric: "bot_share" }), { refreshInterval });
  const hist = useSWR(["histogram", range, filters.metric], () => getHistogram({ ...range, metric: filters.metric }), { refreshInterval });
  const trendGranularity = filters.granularity === "month" ? "month" : "week";
  const trend = useSWR(["trend", range, filters.metric, trendGranularity], () => getTrend({ ...range, metric: filters.metric, granularity: trendGranularity }), { refreshInterval });
  const trendMean = useSWR(["trend-mean", range, filters.metric, trendGranularity], () => getTimeseries({ ...range, metric: filters.metric, granularity: trendGranularity }), { refreshInterval });
  const seasonal = useSWR(["seasonal", range, filters.metric, period], () => getSeasonal({ ...range, metric: filters.metric, period_type: period }), { refreshInterval });
  const correlation = useSWR(["correlation", range], () => getCorrelation(range), { refreshInterval });
  const clusters = useSWR(["analysis-clusters", range], () => getClusters(range), { refreshInterval });
  const c = colors();
  const color = filters.metric === "l7_attack" ? c.l7 : filters.metric === "bot_share" ? c.bot : filters.metric === "human_share" ? c.human : filters.metric === "netflows" ? c.netflow : c.http;
  const dayMap = new Map(clusters.data?.map(row => [row.date, row.cluster_name]));
  const botMap = new Map(bot.data?.map(row => [row.ts, row.mean]));
  const scatterGroups = ["Bình thường", "Cao điểm", "Bất thường", "Chưa phân cụm"].map(name => ({ name, type: "scatter" as const, symbolSize: 10,
    itemStyle: { color: name === "Bất thường" ? c.l7 : name === "Cao điểm" ? c.bot : name === "Bình thường" ? c.human : "#94A3B8" },
    data: scatterTraffic.data?.filter(point => (dayMap.get(vietnamDay(point.ts)) ?? "Chưa phân cụm") === name && point.mean != null && botMap.get(point.ts) != null)
      .map(point => [point.mean!, botMap.get(point.ts)!]) ?? [] }));
  const timeOption: EChartsOption = chartBase({
    xAxis: { type: "category", data: time.data?.map(p => dateLabel(p.ts)) ?? [] },
    yAxis: { type: "value", min: 0, name: metricUnit(filters.metric) },
    series: [{ type: "line", smooth: .25, showSymbol: false, data: time.data?.map(p => p.mean) ?? [], itemStyle: { color }, lineStyle: { width: 3 }, areaStyle: { opacity: .08 } }],
  }, true);
  const histOption: EChartsOption = chartBase({
    xAxis: { type: "category", data: hist.data?.map(p => p.bin_start.toFixed(filters.metric.endsWith("share") ? 0 : 2)) ?? [], axisLabel: { interval: 3 } },
    yAxis: { type: "value", name: "Số mốc" }, tooltip: { trigger: "item" },
    series: [{ type: "bar", barMaxWidth: 23, data: hist.data?.map(p => p.count) ?? [], itemStyle: { color, borderRadius: [3, 3, 0, 0] } }],
  });
  const trendOption: EChartsOption = chartBase({
    legend: { top: 0, right: 0 },
    xAxis: { type: "category", data: trend.data?.map(p => dateLabel(p.ts)) ?? [] },
    yAxis: { type: "value", min: 0, name: metricUnit(filters.metric) },
    series: [
      { name: "Trung bình", type: "line", data: trendMean.data?.map(p => p.mean) ?? [], itemStyle: { color }, showSymbol: false },
      { name: "Xu hướng", type: "line", data: trend.data?.map(p => p.trend_value) ?? [], itemStyle: { color: c.trend }, lineStyle: { type: "dashed", width: 2 }, showSymbol: false },
    ],
  }, true);
  const seasonalLabels = seasonal.data?.map(p => period === "hour_of_day" ? `${String(p.bucket).padStart(2, "0")}:00` : period === "day_of_week" ? ["T2", "T3", "T4", "T5", "T6", "T7", "CN"][p.bucket] : `T${p.bucket}`) ?? [];
  const seasonalOption: EChartsOption = chartBase({ xAxis: { type: "category", data: seasonalLabels }, yAxis: { type: "value", min: 0, name: metricUnit(filters.metric) },
    series: [{ type: "line", smooth: .32, data: seasonal.data?.map(p => p.value) ?? [], itemStyle: { color }, showSymbol: false, lineStyle: { width: 3 } }] });
  const scatterOption: EChartsOption = chartBase({ legend: { top: 0, right: 0 }, tooltip: { trigger: "item" },
    xAxis: { type: "value", name: "HTTP", min: 0 }, yAxis: { type: "value", name: "Bot %", min: 0, max: 100 }, series: scatterGroups }, true);
  const labels = ["http_traffic", "l7_attack", "bot_share", "human_share", "netflows"];
  const short = ["HTTP", "L7", "Bot", "Human", "Netflow"];
  const heatOption: EChartsOption = chartBase({ grid: { left: 85, right: 45, top: 25, bottom: 50 }, tooltip: { trigger: "item" },
    xAxis: { type: "category", data: short, splitArea: { show: true } }, yAxis: { type: "category", data: short, splitArea: { show: true } },
    visualMap: { min: -1, max: 1, calculable: false, orient: "horizontal", bottom: 0, left: "center", inRange: { color: [c.neg, "#FCA5A5", "#F1F5F9", "#67C8DD", c.pos] } },
    series: [{ type: "heatmap", data: correlation.data?.filter(p => p.coef !== null).map(p => [labels.indexOf(p.var_x), labels.indexOf(p.var_y), p.coef]) ?? [], label: { show: true, formatter: (p: { value?: unknown }) => Array.isArray(p.value) ? Number(p.value[2]).toFixed(2) : "" } }],
  });
  return <>
    <PageHeading eyebrow="Khám phá dữ liệu" title="Phân tích dữ liệu">Đối chiếu chuỗi thời gian, phân phối, xu hướng, mùa vụ và tương quan giữa các chỉ số.</PageHeading>
    <DashboardFilters filters={filters} setFilters={setFilters} />
    <p className="notice"><strong>Cách đọc:</strong> HTTP, L7 và Netflow là chỉ số tương đối; Bot và Human là tỷ lệ %. {DATA_MODE === "api" ? "Histogram, mùa vụ và tương quan dùng toàn bộ tập dữ liệu phân tích. Bộ lọc ngày áp dụng cho chuỗi thời gian, xu hướng và phân cụm." : "Đang xem dữ liệu minh họa theo bộ lọc."}</p>
    <div className="grid-half">
      <Panel title="01 · Chuỗi thời gian" subtitle={`${metricLabels[filters.metric]} · ${metricUnit(filters.metric)} · có zoom`}><DataState loading={time.isLoading} error={time.error} empty={!time.data?.length}><DataChart option={timeOption}/></DataState></Panel>
      <Panel title="02 · Phân phối giá trị" subtitle="Histogram · 20 khoảng giá trị"><DataState loading={hist.isLoading} error={hist.error} empty={!hist.data?.length}><DataChart option={histOption}/></DataState></Panel>
      <Panel title="03 · Xu hướng" subtitle={`Đường trend theo ${trendGranularity === "week" ? "tuần" : "tháng"}`}><DataState loading={trend.isLoading || trendMean.isLoading} error={trend.error || trendMean.error} empty={!trend.data?.length}><DataChart option={trendOption}/></DataState></Panel>
      <Panel title="04 · Mùa vụ" subtitle="Trung bình theo giờ, thứ hoặc tháng" action={<select className="input" aria-label="Chu kỳ mùa vụ" value={period} onChange={e => setPeriod(e.target.value as typeof period)}><option value="hour_of_day">Theo giờ</option><option value="day_of_week">Theo thứ</option><option value="month">Theo tháng</option></select>}><DataState loading={seasonal.isLoading} error={seasonal.error} empty={!seasonal.data?.length}><DataChart option={seasonalOption}/></DataState></Panel>
      <Panel title="05 · Lưu lượng và tỷ lệ bot" subtitle="Scatter · màu theo cụm từng ngày · có zoom"><DataState loading={scatterTraffic.isLoading || bot.isLoading || clusters.isLoading} error={scatterTraffic.error || bot.error || clusters.error} empty={!scatterTraffic.data?.length || !bot.data?.length || !clusters.data?.length}><DataChart option={scatterOption}/></DataState></Panel>
      <Panel title="06 · Tương quan Pearson" subtitle="Hệ số trong khoảng −1 đến 1"><DataState loading={correlation.isLoading} error={correlation.error} empty={!correlation.data?.length}><DataChart option={heatOption}/></DataState></Panel>
    </div><div style={{ marginTop: 15 }}><SourceNote /></div>
  </>;
}
