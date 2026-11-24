"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { SWRConfig } from "swr";
import { ApiError, DATA_MODE } from "@/lib/api";

const links = [
  { href: "/", label: "Tổng quan" },
  { href: "/analysis", label: "Phân tích dữ liệu" },
  { href: "/forecast", label: "Dự báo & phân cụm" },
  { href: "/admin", label: "Vận hành hệ thống" },
];

export default function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const preview = DATA_MODE === "demo";
  return <SWRConfig value={{
    shouldRetryOnError: error => !(error instanceof ApiError && [400, 404, 422].includes(error.status)),
    errorRetryCount: 2,
  }}><div className="shell">
    <aside className="sidebar">
      <Link href="/" className="brand"><span className="brand-mark">R</span><span>RADAR / VN</span></Link>
      <div className="sidebar-caption">GIÁM SÁT AN NINH MẠNG</div>
      <nav className="side-nav" aria-label="Điều hướng chính">{links.map(link =>
        <Link key={link.href} href={link.href} aria-current={pathname === link.href ? "page" : undefined} className={`nav-link${pathname === link.href ? " active" : ""}`}>{link.label}</Link>)}</nav>
      <div className="sidebar-source"><span className="minor-label">NGUỒN DỮ LIỆU</span><strong>Cloudflare Radar · Việt Nam</strong><small>Chỉ số tương đối / tỉ lệ %</small></div>
      <div className="sidebar-user"><strong>Dashboard dùng chung</strong><small>{preview ? "Dữ liệu minh họa" : "Dữ liệu từ Backend API"}</small></div>
    </aside>
    <div className="main-column"><header className="topbar"><div className="breadcrumbs"><b>RADAR / VN</b> / {links.find(link => link.href === pathname)?.label ?? "Dashboard"}</div>
      <span className="mode-badge">{preview ? "MÔ PHỎNG · 8 GIÂY" : "API · DỮ LIỆU THẬT"}</span>
    </header><main className="content">{children}</main></div>
  </div></SWRConfig>;
}