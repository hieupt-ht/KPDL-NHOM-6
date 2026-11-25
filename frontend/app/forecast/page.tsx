"use client";
import { useState } from "react";
import { clusterMeasurement, riskSummary } from "@/lib/ml-contract";
import { vietnamDay } from "@/lib/date-utils";
import useSWR from "swr";
import type { EChartsOption } from "echarts";
import { BookOpen, BrainCircuit, Layers, LineChart, ListChecks, ShieldAlert, Sparkles } from "lucide-react";
import DataChart, { areaGradient, chartBase, colors } from "@/components/charts/DataChart";
import DashboardFilters, { useDashboardFilters } from "@/components/filters/DashboardFilters";
import { Chip, DataState, formatDate, formatIndex, formatProbability, PageHeading, Panel, SourceNote } from "@/components/ui/Elements";
import { DATA_REFRESH_INTERVAL, getClusters, getForecastContinuous, getForecastDiscrete, getTimeseries } from "@/lib/api";

const refreshInterval = DATA_REFRESH_INTERVAL;
const tone = (name: string): "danger" | "peak" | "normal" | "info" => name === "Bất thường" ? "danger" : name === "Cao điểm" ? "peak" : name === "Bình thường" ? "normal" : "info";

export default function ForecastPage() {
  const { filters, setFilters } = useDashboardFilters();
  const [selected, setSelected] = useState<string | null>(null);
  const range = { start: filters.start, end: filters.end };
  const forecast = useSWR("forecast-continuous", () => getForecastContinuous(), { refreshInterval });
  const risk = useSWR("forecast-discrete", () => getForecastDiscrete(), { refreshInterval });
  const clusters = useSWR(["clusters", range], () => getClusters(range), { refreshInterval });
  const history = useSWR(["forecast-history", range, filters.granularity], () => getTimeseries({ ...range, granularity: filters.granularity, metric: "http_traffic" }), { refreshInterval });
  const c = colors();
  const active = clusters.data?.find(row => row.date === selected) ?? clusters.data?.at(-1);
  const currentRisk = risk.data?.label === "Cao";
  const clusterColors: Record<string, string> = { "Bình thường": c.human, "Cao điểm": c.bot, "Bất thường": c.l7 };
  const chartOption: EChartsOption = chartBase({
    xAxis: { type: "category", data: clusters.data?.map(row => row.date.slice(5).split("-").reverse().join("/")) ?? [] },
    yAxis: { type: "value", min: 0, name: "Chỉ số HTTP" },
    tooltip: { trigger: "item", formatter: "{b}<br/>HTTP: {c}" },
    series: [{ type: "bar", barMaxWidth: 23, data: clusters.data?.map(row => ({ value: clusterMeasurement(row.features, "http_mean"), itemStyle: { color: clusterColors[row.cluster_name] ?? c.http, borderRadius: [5, 5, 0, 0] } })) ?? [] }],
  }, true);
  const nextDay = forecast.data?.target_date.slice(5).split("-").reverse().join("/");
  const observed = history.data?.map(row => row.mean) ?? [];
  const historyOption: EChartsOption = chartBase({
    legend: { top: 0, right: 0 },
    xAxis: { type: "category", data: [...(history.data?.map(row => vietnamDay(row.ts).slice(5, 10).split("-").reverse().join("/")) ?? []), ...(nextDay ? [nextDay] : [])] },
    yAxis: { type: "value", min: 0, name: "Chỉ số HTTP" },
    series: [{ name: "Đã quan sát", type: "line", smooth: .2, showSymbol: false, itemStyle: { color: c.http }, lineStyle: { width: 3 }, areaStyle: { color: areaGradient(c.http, .22) }, data: observed },
      ...(forecast.data && observed.length ? [{ name: "Dự báo", type: "line" as const, itemStyle: { color: c.netflow }, lineStyle: { type: "dashed" as const, width: 2.5 }, symbolSize: 10,
        data: [...Array(observed.length - 1).fill(null), observed[observed.length - 1], forecast.data.predicted_value] }] : [])],
  }, true);
  return <>
    <PageHeading eyebrow="Mô hình dữ liệu" icon={BrainCircuit} title="Dự báo & phân cụm">Theo dõi kết quả mô hình cho ngày tiếp theo và trạng thái của từng ngày đã quan sát.</PageHeading>
    <div className="grid-half" style={{ marginTop: 0 }}>
      <Panel title="Dự báo lưu lượng ngày mai" icon={Sparkles} subtitle={`Ngày dự báo: ${formatDate(forecast.data?.target_date) || "—"} · chỉ số tương đối`}>
        <DataState loading={forecast.isLoading} error={forecast.error} empty={!forecast.data}><div className="forecast-row"><div className="forecast-number">{formatIndex(forecast.data?.predicted_value)}</div><div><strong>{forecast.data?.model_name}</strong><p className="panel-subtitle">Cập nhật: {formatDate(forecast.data?.created_at)}</p></div></div><p className="panel-subtitle">Giá trị mô hình dự đoán, không phải số request tuyệt đối.</p></DataState>
      </Panel>
      <Panel title="Phân loại rủi ro ngày mai" icon={ShieldAlert} subtitle="P(Cao) · Xác suất thuộc nhóm rủi ro Cao">
        <DataState loading={risk.isLoading} error={risk.error} empty={!risk.data}><div className="forecast-row"><Chip tone={currentRisk ? "danger" : "normal"}>RỦI RO {(risk.data?.label?.toUpperCase() ?? "CHƯA CÓ")}</Chip><strong aria-label={riskSummary(risk.data)} className={currentRisk ? "tone-danger" : "tone-normal"} style={{ fontSize: 40 }}>{formatProbability(risk.data?.probability)}</strong></div><div className="risk-track">{risk.data?.probability != null && <span style={{ width: formatProbability(risk.data.probability) }}/>}</div><p className="panel-subtitle">{risk.data?.model_name}</p></DataState>
      </Panel>
    </div>
    <h2 className="section-title">Trạng thái theo ngày</h2>
    <DashboardFilters filters={filters} setFilters={setFilters} showMetric={false} />
    <div className="grid-main">
      <Panel title="Lịch sử phân cụm" icon={Layers} subtitle="K-Means · bấm vào cột để xem đặc trưng ngày đó · có zoom">
        <DataState loading={clusters.isLoading} error={clusters.error} empty={!clusters.data?.some(row => clusterMeasurement(row.features, "http_mean") != null)}><DataChart option={chartOption} className="chart tall" onEvents={{ click: p => { const row = clusters.data?.[p.dataIndex ?? -1]; if (row) setSelected(row.date); } }}/></DataState>
        <div className="cluster-list" style={{ display: "flex", flexWrap: "wrap" }}><Chip tone="normal">Bình thường</Chip><Chip tone="peak">Cao điểm</Chip><Chip tone="danger">Bất thường</Chip></div>
      </Panel>
      <Panel title="Chi tiết trạng thái" icon={ListChecks} subtitle={active ? `Ngày ${formatDate(active.date)}` : "Chưa chọn ngày"}>
        <DataState loading={clusters.isLoading} error={clusters.error} empty={!active}>
          <div style={{ margin: "25px 0" }}><Chip tone={tone(active?.cluster_name ?? "")}>{active?.cluster_name ?? "—"}</Chip></div>
          <div className="facts"><div className="fact"><span>Lưu lượng trung bình</span><strong>{formatIndex(clusterMeasurement(active?.features, "http_mean"))}</strong></div><div className="fact"><span>L7 cao nhất</span><strong>{formatIndex(clusterMeasurement(active?.features, "l7_max"))}</strong></div><div className="fact"><span>Bot trung bình</span><strong>{formatIndex(clusterMeasurement(active?.features, "bot_mean"))}%</strong></div></div>
          <p className="panel-subtitle" style={{ marginTop: 28 }}>Các thống kê lấy từ Data Mart; đặc trưng lag/rolling của mô hình không thay thế HTTP trung bình, L7 lớn nhất hoặc bot trung bình. Tên cụm mô tả trạng thái dữ liệu, không xác nhận sự cố.</p>
        </DataState>
      </Panel>
    </div>
    <div className="grid-half"><Panel title="Chỉ số lưu lượng lịch sử" icon={LineChart} subtitle="Đối chiếu chuỗi đã quan sát với giá trị dự báo"><DataState loading={history.isLoading} error={history.error} empty={!history.data?.length}><DataChart option={historyOption}/></DataState></Panel>
      <Panel title="Cách đọc kết quả" icon={BookOpen} subtitle="Diễn giải mô hình"><p style={{ marginTop: 22 }}>Phân cụm cho biết ngày trong quá khứ giống trạng thái nào. Dự báo liên tục ước lượng chỉ số lưu lượng ngày mai; phân loại ước lượng mức rủi ro và xác suất.</p><p className="lead">Khi trình bày, đối chiếu với chuỗi L7, tỷ lệ bot và độ mới dữ liệu trước khi kết luận.</p><div style={{ marginTop: 25 }}><SourceNote /></div></Panel></div>
  </>;
}
