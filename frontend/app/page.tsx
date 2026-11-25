"use client";
import { riskSummary } from "@/lib/ml-contract";
import { vietnamDay } from "@/lib/date-utils";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";
import useSWR from "swr";
import type { EChartsOption } from "echarts";
import { toast } from "sonner";
import { Activity, ArrowRight, Bot, CalendarClock, Clock, Gauge, History, LayoutDashboard, Pause, Play, ShieldAlert, Sparkles, TrendingUp, Users } from "lucide-react";
import DataChart, { areaGradient, chartBase, colors } from "@/components/charts/DataChart";
import DashboardFilters, { useDashboardFilters } from "@/components/filters/DashboardFilters";
import { Chip, DataState, formatDate, formatDateTime, formatTimeWithSeconds, formatIndex, Kpi, PageHeading, Panel, SourceNote } from "@/components/ui/Elements";
import { DATA_MODE, DATA_REFRESH_INTERVAL, getClusters, getForecastContinuous, getForecastDiscrete, getStatus, getTimeseries } from "@/lib/api";

const refreshInterval = DATA_REFRESH_INTERVAL;

export default function Home() {
  const { filters, setFilters } = useDashboardFilters();
  const [checkedAt, setCheckedAt] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const previousRisk = useRef<string | null>(null);
  const range = { start: filters.start, end: filters.end };
  const q = { ...range, granularity: filters.granularity };
  const http = useSWR(["http", q], () => getTimeseries({ ...q, metric: "http_traffic" }), { refreshInterval });
  const l7 = useSWR(["l7", q], () => getTimeseries({ ...q, metric: "l7_attack" }), { refreshInterval });
  const bot = useSWR(["bot", q], () => getTimeseries({ ...q, metric: "bot_share" }), { refreshInterval });
  const forecast = useSWR("forecast-continuous", () => getForecastContinuous(), { refreshInterval });
  const risk = useSWR("forecast-discrete", () => getForecastDiscrete(), { refreshInterval, onSuccess(data) {
    if (DATA_MODE === "api" && previousRisk.current === "Thấp" && data.label === "Cao") {
      const message = `Rủi ro dự báo chuyển sang Cao · ${formatDateTime(new Date().toISOString())}. Mở Dự báo để xem kết quả mô hình.`;
      setNotice(message);
      toast.error("Rủi ro ngày mai: Cao", { description: message });
    }
    previousRisk.current = data.label;
  } });
  const cluster = useSWR(["latest-cluster", range], () => getClusters(range), { refreshInterval });
  const status = useSWR("status", () => getStatus(), { refreshInterval, onSuccess() { setCheckedAt(new Date().toISOString()); } });
  const c = colors();
  const [selectedDate, setSelectedDate] = useState<string | null>(null);
  const [playing, setPlaying] = useState(false);
  const [replayDays, setReplayDays] = useState<7 | 30>(7);
  const dates = useMemo(() => http.data?.map(p => vietnamDay(p.ts)) ?? [], [http.data]);
  const replayDates = useMemo(() => dates.slice(-replayDays), [dates, replayDays]);
  const activeDate = selectedDate && dates.includes(selectedDate) ? selectedDate : null;
  const findPoint = (points: typeof http.data) => points?.find(p => vietnamDay(p.ts) === activeDate);
  const latestBot = activeDate ? findPoint(bot.data)?.mean : bot.data?.at(-1)?.mean;
  const latestHttp = activeDate ? findPoint(http.data)?.mean : http.data?.at(-1)?.mean;
  const latestL7 = activeDate ? findPoint(l7.data)?.mean : l7.data?.at(-1)?.mean;
  const latestCluster = cluster.data?.at(-1);
  const selectedCluster = cluster.data?.find(row => row.date === activeDate);
  const anomalies = cluster.data?.filter(row => row.cluster_name === "Bất thường" && dates.includes(row.date)) ?? [];
  const isHigh = risk.data?.label === "Cao";
  useEffect(() => {
    if (!playing || replayDates.length < 2) return;
    const timer = window.setInterval(() => {
      setSelectedDate(current => {
        const index = replayDates.indexOf(current ?? "");
        if (index >= replayDates.length - 1) { setPlaying(false); return current; }
        return replayDates[index + 1];
      });
    }, 1100);
    return () => window.clearInterval(timer);
  }, [playing, replayDates]);
  const changeFilters = (next: Parameters<typeof setFilters>[0]) => {
    setPlaying(false); setSelectedDate(null); setFilters(next);
  };
  const time = (iso: string) => new Intl.DateTimeFormat("vi-VN", { day: "2-digit", month: "2-digit", timeZone: "Asia/Ho_Chi_Minh" }).format(new Date(iso));
  const selectedIndex = activeDate ? dates.indexOf(activeDate) : -1;
  const compare = (points: typeof http.data, unit = "") => {
    if (selectedIndex <= 0) return "Chưa có mốc trước để so sánh";
    const current = points?.find(p => vietnamDay(p.ts) === activeDate)?.mean;
    const previousDate = dates[selectedIndex - 1];
    const previous = points?.find(p => vietnamDay(p.ts) === previousDate)?.mean;
    if (current == null || previous == null) return "Thiếu dữ liệu đối chiếu";
    const change = current - previous;
    return `${change > 0 ? "+" : ""}${formatIndex(change)}${unit} so với ${formatDate(previousDate)}`;
  };
  const option: EChartsOption = chartBase({
    legend: { top: 2, right: 0 },
    xAxis: { type: "category", data: http.data?.map(point => time(point.ts)) ?? [] },
    yAxis: { type: "value", min: 0 },
    series: [
      { name: "HTTP", type: "line", smooth: .24, showSymbol: false, lineStyle: { width: 3, shadowColor: c.http + "66", shadowBlur: 10, shadowOffsetY: 4 }, itemStyle: { color: c.http }, areaStyle: { color: areaGradient(c.http, .26) }, data: http.data?.map(p => p.mean) ?? [],
        markLine: selectedIndex < 0 ? undefined : { silent: true, symbol: "none", label: { show: false }, lineStyle: { color: c.axis, type: "dashed" }, data: [{ xAxis: selectedIndex }] } },
      { name: "L7", type: "line", smooth: .24, showSymbol: false, lineStyle: { width: 2.5 }, itemStyle: { color: c.l7 }, areaStyle: { color: areaGradient(c.l7, .14) }, data: l7.data?.map(p => p.mean) ?? [] },
    ],
  }, true);
  return <>
    <PageHeading eyebrow="Tổng quan" icon={LayoutDashboard} title="Tình hình lưu lượng tại Việt Nam">Theo dõi lưu lượng HTTP, tín hiệu tấn công L7 và kết quả dự báo từ Cloudflare Radar.</PageHeading>
    <div className="freshness-bar" role="status"><span><Clock size={14} />{DATA_MODE === "demo" ? "Mô phỏng lúc" : "Kiểm tra lúc"} <strong>{checkedAt ? DATA_MODE === "demo" ? formatTimeWithSeconds(checkedAt) : formatDateTime(checkedAt) : "Chưa kiểm tra"}</strong></span><span><CalendarClock size={14} />Dữ liệu mới nhất <strong>{formatDateTime(status.data?.data_freshness?.latest_silver_ts)}</strong></span><small>{DATA_MODE === "demo" ? "Mô phỏng cập nhật điểm cuối mỗi 8 giây · mốc dữ liệu giữ nguyên" : "Tự kiểm tra lại sau mỗi 5 phút"}</small></div>
    {notice && <div className="risk-notice" role="status">{notice} <button type="button" onClick={() => setNotice(null)} aria-label="Đóng thông báo">×</button></div>}
    <DashboardFilters filters={filters} setFilters={changeFilters} showMetric={false} />
    {activeDate && <div className="history-banner" role="status">Đang xem dữ liệu lịch sử ngày {formatDate(activeDate)} · KPI lưu lượng, L7 và bot ở mốc này <button type="button" onClick={() => { setPlaying(false); setSelectedDate(null); }}>Về dữ liệu mới nhất</button></div>}
    <div className="kpi-grid">
      <Kpi label="Chỉ số lưu lượng" value={formatIndex(latestHttp)} note="Giá trị tương đối, không phải số request" tone="tone-primary" icon={Activity} />
      <Kpi label="Chỉ số tấn công L7" value={formatIndex(latestL7)} note="Theo khoảng thời gian đang chọn" tone="tone-danger" icon={ShieldAlert} />
      <Kpi label="Tỷ lệ bot" value={latestBot == null ? "—" : `${formatIndex(latestBot)}%`} note="Trong lưu lượng HTTP" tone="tone-bot" icon={Bot} />
      <Kpi label="Rủi ro ngày mai" value={risk.data ? riskSummary(risk.data) : "—"} note="Dự báo mới nhất, không thuộc mốc phát lại" tone={isHigh ? "tone-danger" : "tone-normal"} icon={Gauge} />
    </div>
    <div className="grid-main">
      <Panel title="Lưu lượng & tấn công theo thời gian" icon={TrendingUp} subtitle="Chỉ số tương đối · Kéo thanh dưới hoặc cuộn trên biểu đồ để zoom">
        <DataState loading={http.isLoading || l7.isLoading} error={http.error || l7.error} empty={!http.data?.length || !l7.data?.length}><DataChart option={option} className="chart tall" onEvents={{ click: ({ dataIndex }) => { if (dataIndex != null && dates[dataIndex]) { setPlaying(false); setSelectedDate(dates[dataIndex]); } } }} /></DataState>
      </Panel>
      <section className="panel insight"><div className="panel-head-main"><span className="panel-icon"><Sparkles size={16} /></span><div><h2 className="panel-title">Nhận định nhanh</h2><p className="panel-subtitle">Từ kết quả phân tích trong khoảng đã chọn</p></div></div>
        <div style={{ marginTop: 24 }}><Chip tone={latestCluster?.cluster_name === "Bất thường" ? "danger" : "info"}>{latestCluster?.cluster_name ?? "Chưa có trạng thái"}</Chip>
          <h3>{latestCluster ? `Ngày gần nhất: ${latestCluster.cluster_name.toLowerCase()}` : "Chưa có kết quả phân cụm"}</h3>
          <p>Đối chiếu xu hướng L7, tỷ lệ bot và phân cụm để đánh giá biến động. Nhãn mô hình không xác nhận một sự cố đã xảy ra.</p></div>
        <hr/><div className="minor-label">DỮ LIỆU MỚI NHẤT</div><strong>{formatDate(status.data?.data_freshness?.latest_silver_ts)}</strong>
        <div className="insight-bottom"><SourceNote /></div>
      </section>
    </div>
    <Panel title="Dòng thời gian bất thường" icon={History} subtitle="Các ngày được mô hình phân cụm gắn nhãn Bất thường · Chọn mốc để đối chiếu các chỉ số" className="timeline-panel"
      action={<div className="replay-controls"><label htmlFor="replay-days">Phạm vi phát lại</label><select id="replay-days" className="input" value={replayDays} onChange={e => { setPlaying(false); setReplayDays(Number(e.target.value) as 7 | 30); }}><option value={7}>7 ngày</option><option value={30}>30 ngày</option></select><button type="button" className="button primary" disabled={filters.granularity !== "day" || replayDates.length < 2 || !!http.error} onClick={() => { if (playing) setPlaying(false); else { if (!replayDates.includes(activeDate ?? "") || activeDate === replayDates.at(-1)) setSelectedDate(replayDates[0]); setPlaying(true); } }}>{playing ? <><Pause size={14} /> Tạm dừng</> : <><Play size={14} /> Phát lại dữ liệu lịch sử</>}</button></div>}>
      {filters.granularity !== "day" ? <div className="notice">Dòng thời gian và phát lại cần độ phân giải <strong>Ngày</strong>. Chọn “Ngày” ở bộ lọc để xem từng mốc.</div> : <DataState loading={cluster.isLoading || http.isLoading} error={cluster.error || http.error} empty={!dates.length}>
        <div className="timeline-track" aria-label="Các mốc thời gian">{dates.map(date => { const anomaly = anomalies.some(row => row.date === date); return <button type="button" key={date} className={`timeline-day${anomaly ? " anomaly" : ""}${activeDate === date ? " selected" : ""}`} aria-pressed={activeDate === date} title={`${formatDate(date)}${anomaly ? " · Bất thường" : ""}`} onClick={() => { setPlaying(false); setSelectedDate(date); }}><span className="timeline-mark"/><small>{time(`${date}T00:00:00Z`)}</small></button>; })}</div>
        <div className="timeline-legend"><span><i className="legend-dot"/> Ngày có dữ liệu</span><span><i className="legend-dot anomaly"/> Phân cụm bất thường</span><span>Chọn một ngày trên biểu đồ hoặc dòng thời gian</span></div>
        {activeDate && <div className="history-detail"><div><span className="minor-label">CHI TIẾT NGÀY {formatDate(activeDate)}</span><h3>{selectedCluster ? `Cụm: ${selectedCluster.cluster_name}` : "Chưa có kết quả phân cụm cho ngày này"}</h3><p>{selectedCluster ? "Nhãn do mô hình phân cụm cung cấp; đối chiếu các chỉ số bên cạnh để hiểu biến động." : "Các chỉ số được hiển thị từ chuỗi thời gian. Chưa thể giải thích nhãn cụm khi không có kết quả phân cụm."}</p></div><dl><div><dt>HTTP · chỉ số</dt><dd>{formatIndex(findPoint(http.data)?.mean)}</dd><small>{compare(http.data)}</small></div><div><dt>L7 · chỉ số</dt><dd>{formatIndex(findPoint(l7.data)?.mean)}</dd><small>{compare(l7.data)}</small></div><div><dt>Bot · %</dt><dd>{findPoint(bot.data) ? `${formatIndex(findPoint(bot.data)?.mean)}%` : "—"}</dd><small>{compare(bot.data, " điểm %")}</small></div></dl></div>}
        <SourceNote />
      </DataState>}
    </Panel>
    <div className="grid-half">
      <Panel title="Bot và người dùng" icon={Users} subtitle="Tỷ lệ phần trăm trong lưu lượng HTTP">
        <DataState loading={bot.isLoading} error={bot.error} empty={latestBot == null}>
          <div className="distribution-labels"><span style={{ color: c.bot }}>Bot {formatIndex(latestBot)}%</span><span>Người dùng {formatIndex(latestBot == null ? undefined : 100 - latestBot)}%</span></div>
          <div className="distribution"><span style={{ width: `${Math.min(100, Math.max(0, latestBot ?? 0))}%` }} /><i /></div>
          <p className="panel-subtitle" style={{ marginTop: 20 }}>Nguồn dữ liệu: bot_class · Cloudflare Radar</p>
        </DataState>
      </Panel>
      <Panel title="Dự báo ngày mai" icon={Sparkles} subtitle="Dự báo tương đối và xác suất rủi ro từ mô hình">
        <DataState loading={forecast.isLoading || risk.isLoading} error={forecast.error || risk.error} empty={!forecast.data || !risk.data}>
          <div className="forecast-row"><div><div className="forecast-number">{formatIndex(forecast.data?.predicted_value)}</div><span className="panel-subtitle">Chỉ số lưu lượng dự báo</span></div><Chip tone={isHigh ? "danger" : "normal"}>RỦI RO {riskSummary(risk.data)}</Chip></div>
          <Link href="/forecast" className="button">Xem dự báo & phân cụm <ArrowRight size={15} /></Link>
        </DataState>
      </Panel>
    </div>
  </>;
}
