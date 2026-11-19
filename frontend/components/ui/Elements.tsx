"use client";
import type { ReactNode } from "react";
import { ApiError, DATA_MODE } from "@/lib/api";

export function PageHeading({ eyebrow, title, children }: { eyebrow: string; title: string; children: ReactNode }) {
  return <div className="page-header"><div><span className="eyebrow">{eyebrow}</span><h1>{title}</h1><p className="lead">{children}</p></div></div>;
}
export function Panel({ title, subtitle, action, children, className = "" }: {
  title: string; subtitle?: string; action?: ReactNode; children: ReactNode; className?: string;
}) {
  return <section className={`panel panel-body ${className}`}><div className="panel-head"><div><h2 className="panel-title">{title}</h2>{subtitle && <p className="panel-subtitle">{subtitle}</p>}</div>{action}</div>{children}</section>;
}
export function Kpi({ label, value, note, tone = "" }: { label: string; value: string; note: string; tone?: string }) {
  return <div className="panel kpi"><div className="kpi-label">{label}</div><strong key={value} className={`kpi-value kpi-change ${tone}`}>{value}</strong><div className="kpi-note">{note}</div></div>;
}
export function Chip({ children, tone = "info" }: { children: ReactNode; tone?: "info" | "danger" | "normal" | "peak" }) {
  return <span className={`status-chip ${tone}`}>{children}</span>;
}
export function DataState({ loading, error, empty, children }: {
  loading?: boolean; error?: Error; empty?: boolean; children: ReactNode;
}) {
  if (loading) return <div className="empty-state" role="status"><strong>Đang tải dữ liệu…</strong><small>Đang đọc kết quả từ Data Mart.</small></div>;
  if ((empty && !error) || (error instanceof ApiError && error.status === 404)) return <div className="empty-state"><strong>Chưa có dữ liệu</strong><small>Thử đổi khoảng thời gian hoặc chờ tác vụ phân tích hoàn thành.</small></div>;
  if (error) return <div className="empty-state" role="alert"><strong>Chưa hiển thị được dữ liệu</strong><small>{error.message}</small></div>;
  return <>{children}</>;
}
export function SourceNote() { return <small className="panel-subtitle">{DATA_MODE === "demo" ? "Dữ liệu minh họa · điểm cuối mô phỏng thay đổi mỗi 8 giây" : "Nguồn: Cloudflare Radar · Data Mart"}</small>; }
export const formatIndex = (n?: number | null) => n == null || !Number.isFinite(n) ? "—" : n.toLocaleString("vi-VN", { maximumFractionDigits: 2 });
export const formatProbability = (n?: number | null) => n == null || !Number.isFinite(n) ? "—" : `${Math.round(n * 100)}%`;
export const formatDate = (iso?: string | null) => iso ? new Intl.DateTimeFormat("vi-VN", { timeZone: "Asia/Ho_Chi_Minh", day: "2-digit", month: "2-digit", year: "numeric" }).format(new Date(iso)) : "—";
export const formatDateTime = (iso?: string | null) => iso ? new Intl.DateTimeFormat("vi-VN", { timeZone: "Asia/Ho_Chi_Minh", day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(iso)) + " ICT" : "—";
export const formatTimeWithSeconds = (iso?: string | null) => iso ? new Intl.DateTimeFormat("vi-VN", { timeZone: "Asia/Ho_Chi_Minh", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(new Date(iso)) + " ICT" : "—";
