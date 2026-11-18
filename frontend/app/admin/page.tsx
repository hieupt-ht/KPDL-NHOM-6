"use client";
import Link from "next/link";
import { useState } from "react";
import useSWR from "swr";
import { usePreviewRole } from "@/components/layout/AppShell";
import { Chip, DataState, formatDate, PageHeading, Panel } from "@/components/ui/Elements";
import { DATA_MODE, getStatus, runJob } from "@/lib/api";

const services = [
  { id: "analysis", title: "Data Analysis", frequency: "5 phút/lần", note: "Tổng hợp, histogram, trend, seasonal, correlation" },
  { id: "clustering", title: "Clustering", frequency: "1 ngày/lần", note: "K-Means · phân cụm trạng thái từng ngày" },
  { id: "prediction", title: "Prediction", frequency: "5 phút/lần", note: "Dự báo liên tục và phân loại rủi ro" },
] as const;

export default function AdminPage() {
  const { role } = usePreviewRole();
  const { data, error, isLoading, mutate } = useSWR(role === "admin" ? "admin-status" : null, () => getStatus(), { refreshInterval: DATA_MODE === "api" ? 300_000 : 0 });
  const [running, setRunning] = useState<string | null>(null);
  const [feedback, setFeedback] = useState<string | null>(null);
  if (role !== "admin") return <div className="panel access-state"><span className="eyebrow">Vai trò Viewer</span><h1>Trang dành cho Admin</h1><p className="lead">Tài khoản Viewer xem được dashboard và các kết quả phân tích. Chuyển sang vai trò Admin xem thử ở góc trên để xem giao diện vận hành.</p><p className="panel-subtitle" style={{ marginTop: 20 }}>Công tắc vai trò hiện chỉ phục vụ trình diễn UI, chưa phải đăng nhập hoặc phân quyền thật.</p><Link href="/" className="button">Về Tổng quan</Link></div>;
  async function execute(service: "analysis" | "clustering" | "prediction") {
    setRunning(service); setFeedback(null);
    try { await runJob(service); setFeedback(`Đã gửi yêu cầu chạy ${service}. Đang đọc trạng thái mới…`); await mutate(); }
    catch (e) { setFeedback(e instanceof Error ? e.message : "Không gửi được yêu cầu chạy job."); }
    finally { setRunning(null); }
  }
  return <>
    <PageHeading eyebrow="Quản trị · Admin" title="Vận hành dữ liệu">Theo dõi độ mới của Data Mart, lịch sử tác vụ và kích hoạt lại các job khi cần.</PageHeading>
    <div className="notice" role="note"><strong>{DATA_MODE === "demo" ? "Chế độ minh họa:" : "Chế độ API:"}</strong> {DATA_MODE === "demo" ? "Các nút chạy job bị khóa vì không có backend thật. Đổi sang chế độ API sau khi nhóm backend hoàn thiện." : "Tác vụ sẽ gửi POST tới API. Khi tích hợp SSO, backend phải kiểm tra role admin."}</div>
    <div className="service-grid" style={{ marginTop: 17 }}>{services.map(service => {
      const latest = data?.service_runs.find(row => row.service === service.id);
      return <section className="panel service-card" key={service.id}>
        <div className="service-meta"><div><h2>{service.title}</h2><span className="panel-subtitle">{service.frequency}</span></div><Chip tone={latest?.status === "success" ? "normal" : "peak"}>{latest?.status === "success" ? "Hoàn tất" : latest?.status ?? "Chưa có dữ liệu"}</Chip></div>
        <div className="minor-label">LẦN CHẠY GẦN NHẤT</div><div style={{ fontSize: 21, fontWeight: 800, margin: "5px 0 12px" }}>{formatDate(latest?.finished_at)}</div>
        <div className="service-footer"><span className="panel-subtitle">{service.note}</span><button type="button" className="button primary" disabled={DATA_MODE === "demo" || running !== null} onClick={() => execute(service.id)}>{running === service.id ? "Đang gửi…" : "Chạy lại"}</button></div>
      </section>;
    })}</div>
    {feedback && <p className="job-feedback" role="status">{feedback}</p>}
    <div className="grid-half">
      <Panel title="Tình trạng dữ liệu" subtitle="Thông tin mới nhất do API đọc từ Gold">
        <DataState loading={isLoading} error={error} empty={!data}><div className="facts" style={{ marginTop: 24 }}>
          <div className="fact"><span>Data Mart · Gold</span><Chip tone="normal">Có dữ liệu</Chip></div>
          <div className="fact"><span>Mốc Silver mới nhất</span><strong>{formatDate(data?.data_freshness?.latest_silver_ts)}</strong></div>
          <div className="fact"><span>Số lần chạy hiển thị</span><strong>{data?.service_runs.length ?? 0}</strong></div>
        </div></DataState>
      </Panel>
      <Panel title="Luồng hệ thống" subtitle="Kiến trúc theo đề tài"><div className="cluster-list">
        {["Cloudflare Radar → Data Ingestion", "Warehouse · Bronze → Silver", "Analysis / Clustering / Prediction → Mart · Gold", "FastAPI → Dashboard"].map((item, i) => <div className="cluster-row" key={item}><span>{item}</span><span className="minor-label">0{i + 1}</span></div>)}
      </div></Panel>
    </div>
    <div style={{ marginTop: 16 }}><Panel title="Lịch sử tác vụ" subtitle="Các lần chạy gần đây từ gold.service_runs"><DataState loading={isLoading} error={error} empty={!data?.service_runs.length}>
      <div className="table-wrap"><table className="table"><thead><tr><th>Tác vụ</th><th>Bắt đầu</th><th>Kết thúc</th><th>Trạng thái</th><th>Ghi chú</th></tr></thead><tbody>{data?.service_runs.map(run => <tr key={run.id}><td><strong>{run.service}</strong></td><td>{formatDate(run.started_at)}</td><td>{formatDate(run.finished_at)}</td><td><Chip tone={run.status === "success" ? "normal" : "peak"}>{run.status}</Chip></td><td>{run.error ?? "—"}</td></tr>)}</tbody></table></div>
    </DataState></Panel></div>
  </>;
}
