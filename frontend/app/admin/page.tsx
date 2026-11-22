"use client";
import { useEffect, useState } from "react";
import useSWR from "swr";
import { Chip, DataState, formatDate, PageHeading, Panel } from "@/components/ui/Elements";
import { ApiError, DATA_MODE, getJobRun, getStatus, runJob } from "@/lib/api";
import type { AcceptedJob, ServiceRun } from "@/types/api";

const services = [
  { id: "analysis", title: "Data Analysis", frequency: "5 phút/lần", note: "Tổng hợp, histogram, trend, seasonal, correlation" },
  { id: "clustering", title: "Clustering", frequency: "1 ngày/lần", note: "K-Means · phân cụm trạng thái từng ngày" },
  { id: "prediction", title: "Prediction", frequency: "5 phút/lần", note: "Dự báo liên tục và phân loại rủi ro" },
] as const;
const statusLabel = (value: string | null | undefined) => (({ running: "Đang chạy", success: "Hoàn tất", failed: "Thất bại", partial: "Hoàn tất một phần", skipped: "Đã bỏ qua", interrupted: "Bị gián đoạn" } as Record<string, string>)[value ?? ""] ?? value ?? "Chưa có dữ liệu");

export default function AdminPage() {
  const isDemo = DATA_MODE === "demo";
  const { data, error, isLoading, mutate } = useSWR("admin-status", () => getStatus(), { refreshInterval: DATA_MODE === "api" ? 300_000 : 0 });
  const [sending, setSending] = useState<string | null>(null);
  const [pending, setPending] = useState<AcceptedJob | null>(null);
  const [tracked, setTracked] = useState<ServiceRun[]>([]);
  const [feedback, setFeedback] = useState<string | null>(null);
  useEffect(() => {
    if (!pending) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const row = await getJobRun(pending!.run_id);
        if (stopped) return;
        setTracked(old => [row, ...old.filter(item => item.id !== row.id)]);
        // A failure loading the summary must not hide a known terminal result.
        void mutate().catch(() => {});
        if (row.status !== "running") {
          setPending(null);
          setFeedback(`Lần chạy #${row.id}: ${statusLabel(row.status)}.${row.error ? ` ${row.error}` : ""}`);
          return;
        }
      } catch (e) {
        if (stopped) return;
        setFeedback(e instanceof Error ? e.message : "Chưa đọc được trạng thái tác vụ.");
        if (e instanceof ApiError && [401, 403, 404].includes(e.status)) { setPending(null); return; }
      }
      if (!stopped) timer = setTimeout(() => void poll(), 2000);
    }
    void poll();
    return () => { stopped = true; clearTimeout(timer); };
  }, [pending, mutate]);
  async function execute(service: "analysis" | "clustering" | "prediction") {
    setSending(service); setFeedback(null);
    try {
      const accepted = await runJob(service);
      setPending(accepted);
      setFeedback(`Đã nhận lần chạy #${accepted.run_id} của ${service}. Đang chờ kết quả…`);
      await mutate();
    } catch (e) { setFeedback(e instanceof Error ? e.message : "Không gửi được yêu cầu chạy job."); }
    finally { setSending(null); }
  }
  const rows = [...new Map([...(data?.service_runs ?? []), ...tracked].map(row => [row.id, row])).values()].sort((a, b) => b.id - a.id);
  return <>
    <PageHeading eyebrow="Vận hành hệ thống" title="Vận hành dữ liệu">Theo dõi độ mới của Data Mart và kết quả thực thi từng tác vụ.</PageHeading>
    <div className="notice" role="note"><strong>{isDemo ? "Chế độ minh họa:" : "Vận hành tác vụ:"}</strong> {isDemo ? "Các nút chạy job bị khóa. Dữ liệu hiện tại là minh họa." : "Yêu cầu được tiếp nhận trước khi tác vụ hoàn tất. Kết quả được đọc lại theo đúng mã lần chạy."}</div>
    <div className="service-grid" style={{ marginTop: 17 }}>{services.map(service => {
      const latest = rows.find(row => row.service === service.id);
      return <section className="panel service-card" key={service.id}>
        <div className="service-meta"><div><h2>{service.title}</h2><span className="panel-subtitle">{service.frequency}</span></div><Chip tone={latest?.status === "success" ? "normal" : latest?.status === "failed" ? "danger" : "peak"}>{statusLabel(latest?.status)}</Chip></div>
        <div className="minor-label">LẦN CHẠY GẦN NHẤT</div><div style={{ fontSize: 21, fontWeight: 800, margin: "5px 0 12px" }}>{formatDate(latest?.finished_at)}</div>
        <div className="service-footer"><span className="panel-subtitle">{service.note}</span><button type="button" className="button primary" disabled={isDemo || sending !== null || pending !== null} onClick={() => void execute(service.id)}>{sending === service.id ? "Đang gửi…" : pending?.service === service.id ? "Đang theo dõi…" : "Chạy lại"}</button></div>
      </section>;
    })}</div>
    {feedback && <p className="job-feedback" role="status">{feedback}</p>}
    {pending && <button className="button" onClick={() => { setTracked(old => old.filter(row => row.id !== pending.run_id)); setPending(null); void mutate().catch(() => {}); setFeedback("Đã dừng theo dõi. Tác vụ vẫn tiếp tục ở backend."); }}>Dừng theo dõi</button>}
    <div className="grid-half"><Panel title="Tình trạng dữ liệu" subtitle="Kết quả và độ mới đọc từ Gold">
      <DataState loading={isLoading} error={error} empty={!data}><div className="facts" style={{ marginTop: 24 }}>
        <div className="fact"><span>Kết quả phân tích</span><Chip tone={data?.data_freshness ? "normal" : "peak"}>{data?.data_freshness ? "Đã có mốc cập nhật" : "Chưa có mốc cập nhật"}</Chip></div>
        <div className="fact"><span>Mốc Silver mới nhất</span><strong>{formatDate(data?.data_freshness?.latest_silver_ts)}</strong></div>
        <div className="fact"><span>Số lần chạy hiển thị</span><strong>{rows.length}</strong></div>
      </div></DataState></Panel>
      <Panel title="Luồng hệ thống" subtitle="Kiến trúc theo đề tài"><div className="cluster-list">{["Cloudflare Radar → Data Ingestion", "Warehouse · Bronze → Silver", "Analysis / Clustering / Prediction → Mart · Gold", "FastAPI → Dashboard"].map((item, i) => <div className="cluster-row" key={item}><span>{item}</span><span className="minor-label">0{i + 1}</span></div>)}</div></Panel>
    </div>
    <div style={{ marginTop: 16 }}><Panel title="Nhật ký tác vụ" subtitle="Lần chạy mới nhất của từng service và các lần đang theo dõi trong phiên này"><DataState loading={isLoading} error={error} empty={!rows.length}>
      <div className="table-wrap"><table className="table"><thead><tr><th>Mã / Tác vụ</th><th>Bắt đầu</th><th>Kết thúc</th><th>Trạng thái</th><th>Ghi chú</th></tr></thead><tbody>{rows.map(run => <tr key={run.id}><td><strong>#{run.id} · {run.service}</strong></td><td>{formatDate(run.started_at)}</td><td>{formatDate(run.finished_at)}</td><td><Chip tone={run.status === "success" ? "normal" : run.status === "failed" ? "danger" : "peak"}>{statusLabel(run.status)}</Chip></td><td>{run.error ?? "—"}</td></tr>)}</tbody></table></div>
    </DataState></Panel></div>
  </>;
}
