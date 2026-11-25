"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { SWRConfig } from "swr";
import { Toaster } from "sonner";
import { Activity, BarChart3, BrainCircuit, Database, LayoutDashboard, Moon, Radar, Server, Sun } from "lucide-react";
import { ApiError, DATA_MODE } from "@/lib/api";
import { ThemeProvider, useTheme } from "@/components/theme/ThemeProvider";

const links = [
  { href: "/", label: "Tổng quan", icon: LayoutDashboard },
  { href: "/analysis", label: "Phân tích dữ liệu", icon: BarChart3 },
  { href: "/forecast", label: "Dự báo & phân cụm", icon: BrainCircuit },
  { href: "/admin", label: "Vận hành hệ thống", icon: Server },
];

function ThemeToggle() {
  const { theme, toggle } = useTheme();
  const dark = theme === "dark";
  return <button type="button" className="icon-button" onClick={toggle} aria-label={dark ? "Chuyển sang giao diện sáng" : "Chuyển sang giao diện tối"} title={dark ? "Giao diện sáng" : "Giao diện tối"}>
    {dark ? <Sun size={17} /> : <Moon size={17} />}
  </button>;
}

function Shell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const { theme } = useTheme();
  const preview = DATA_MODE === "demo";
  const current = links.find(link => link.href === pathname);
  return <div className="shell">
    <aside className="sidebar">
      <Link href="/" className="brand"><span className="brand-mark"><Radar size={19} strokeWidth={2.2} /></span><span className="brand-text"><b>RADAR</b><small>Việt Nam</small></span></Link>
      <div className="sidebar-caption">Giám sát an ninh mạng</div>
      <nav className="side-nav" aria-label="Điều hướng chính">{links.map(({ href, label, icon: Icon }) =>
        <Link key={href} href={href} aria-current={pathname === href ? "page" : undefined} className={`nav-link${pathname === href ? " active" : ""}`}><Icon size={18} strokeWidth={2} /><span>{label}</span></Link>)}</nav>
      <div className="sidebar-source"><span className="minor-label"><Database size={12} /> Nguồn dữ liệu</span><strong>Cloudflare Radar · VN</strong><small>Chỉ số tương đối / tỉ lệ %</small></div>
      <div className="sidebar-user"><span className={`live-dot${preview ? " demo" : ""}`} aria-hidden /><div><strong>Dashboard dùng chung</strong><small>{preview ? "Dữ liệu minh họa" : "Dữ liệu từ Backend API"}</small></div></div>
    </aside>
    <div className="main-column">
      <header className="topbar">
        <div className="breadcrumbs"><Activity size={15} /><b>RADAR / VN</b><span>/</span><span className="crumb-current">{current?.label ?? "Dashboard"}</span></div>
        <div className="top-actions">
          <span className={`mode-badge${preview ? " demo" : ""}`}><span className={`live-dot${preview ? " demo" : ""}`} aria-hidden />{preview ? "MÔ PHỎNG · 8 GIÂY" : "API · DỮ LIỆU THẬT"}</span>
          <ThemeToggle />
        </div>
      </header>
      {/* key theo theme để biểu đồ ECharts đọc lại bảng màu CSS; SWR giữ cache nên không tải lại dữ liệu. */}
      <main className="content" key={theme}>{children}</main>
    </div>
    <Toaster theme={theme} position="bottom-right" richColors closeButton />
  </div>;
}

export default function AppShell({ children }: { children: ReactNode }) {
  return <SWRConfig value={{
    shouldRetryOnError: error => !(error instanceof ApiError && [400, 404, 422].includes(error.status)),
    errorRetryCount: 2,
  }}><ThemeProvider><Shell>{children}</Shell></ThemeProvider></SWRConfig>;
}
