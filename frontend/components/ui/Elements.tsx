"use client";
import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";
import { AlertTriangle, Inbox, Loader2 } from "lucide-react";
import { ApiError, DATA_MODE } from "@/lib/api";

export function PageHeading({ eyebrow, title, icon: Icon, children }: { eyebrow: string; title: string; icon?: LucideIcon; children: ReactNode }) {
  return <div className="page-header"><div className="page-header-main">{Icon && <span className="page-icon"><Icon size={22} /></span>}<div><span className="eyebrow">{eyebrow}</span><h1>{title}</h1><p className="lead">{children}</p></div></div></div>;
}
export function Panel({ title, subtitle, action, icon: Icon, children, className = "" }: {
  title: string; subtitle?: string; action?: ReactNode; icon?: LucideIcon; children: ReactNode; className?: string;
}) {
  return <section className={`panel panel-body ${className}`}><div className="panel-head"><div className="panel-head-main">{Icon && <span className="panel-icon"><Icon size={16} /></span>}<div><h2 className="panel-title">{title}</h2>{subtitle && <p className="panel-subtitle">{subtitle}</p>}</div></div>{action}</div>{children}</section>;
}
export function Kpi({ label, value, note, tone = "", icon: Icon }: { label: string; value: string; note: string; tone?: string; icon?: LucideIcon }) {
  return <div className={`panel kpi ${tone}`}><div className="kpi-top"><div className="kpi-label">{label}</div>{Icon && <span className="kpi-icon"><Icon size={17} /></span>}</div><strong key={value} className={`kpi-value kpi-change${value.length > 9 ? " long" : ""}`}>{value}</strong><div className="kpi-note">{note}</div></div>;
}
export function Chip({ children, tone = "info" }: { children: ReactNode; tone?: "info" | "danger" | "normal" | "peak" }) {
  return <span className={`status-chip ${tone}`}><i aria-hidden />{children}</span>;
}
export function DataState({ loading, error, empty, children }: {
  loading?: boolean; error?: Error; empty?: boolean; children: ReactNode;
}) {
  if (loading) return <div className="empty-state loading" role="status"><div className="skeleton-bars" aria-hidden>{Array.from({ length: 9 }, (_, i) => <span key={i} style={{ animationDelay: `${i * 90}ms` }} />)}</div><strong><Loader2 size={14} className="spin" /> Đang tải dữ liệu…</strong><small>Đang đọc kết quả từ Data Mart.</small></div>;
  if ((empty && !error) || (error instanceof ApiError && error.status === 404)) return <div className="empty-state"><span className="empty-icon"><Inbox size={20} /></span><strong>Chưa có dữ liệu</strong><small>Thử đổi khoảng thời gian hoặc chờ tác vụ phân tích hoàn thành.</small></div>;
  if (error) return <div className="empty-state error" role="alert"><span className="empty-icon"><AlertTriangle size={20} /></span><strong>Chưa hiển thị được dữ liệu</strong><small>{error.message}</small></div>;
  return <>{children}</>;
}
export function SourceNote() { return <small className="panel-subtitle source-note">{DATA_MODE === "demo" ? "Dữ liệu minh họa · điểm cuối mô phỏng thay đổi mỗi 8 giây" : "Nguồn: Cloudflare Radar · Data Mart"}</small>; }
export const formatIndex = (n?: number | null) => n == null || !Number.isFinite(n) ? "—" : n.toLocaleString("vi-VN", { maximumFractionDigits: 2 });
export const formatProbability = (n?: number | null) => n == null || !Number.isFinite(n) ? "—" : `${Math.round(n * 100)}%`;
export const formatDate = (iso?: string | null) => iso ? new Intl.DateTimeFormat("vi-VN", { timeZone: "Asia/Ho_Chi_Minh", day: "2-digit", month: "2-digit", year: "numeric" }).format(new Date(iso)) : "—";
export const formatDateTime = (iso?: string | null) => iso ? new Intl.DateTimeFormat("vi-VN", { timeZone: "Asia/Ho_Chi_Minh", day: "2-digit", month: "2-digit", year: "numeric", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(iso)) + " ICT" : "—";
export const formatTimeWithSeconds = (iso?: string | null) => iso ? new Intl.DateTimeFormat("vi-VN", { timeZone: "Asia/Ho_Chi_Minh", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(new Date(iso)) + " ICT" : "—";
