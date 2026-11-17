"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { createContext, useContext, useState, type ReactNode } from "react";
import { DATA_MODE } from "@/lib/api";

type Role = "viewer" | "admin";
const RoleContext = createContext<{ role: Role; setRole: (role: Role) => void }>({ role: "viewer", setRole: () => {} });
export const usePreviewRole = () => useContext(RoleContext);
const links = [
  { href: "/", label: "Tổng quan" },
  { href: "/analysis", label: "Phân tích dữ liệu" },
  { href: "/forecast", label: "Dự báo & phân cụm" },
  { href: "/admin", label: "Vận hành hệ thống" },
];
export default function AppShell({ children }: { children: ReactNode }) {
  const pathname = usePathname();
  const [role, setRole] = useState<Role>("viewer");
  const changeRole = (next: Role) => { setRole(next); };
  return <RoleContext.Provider value={{ role, setRole: changeRole }}><div className="shell">
    <aside className="sidebar">
      <Link href="/" className="brand"><span className="brand-mark">R</span><span>RADAR / VN</span></Link>
      <div className="sidebar-caption">GIÁM SÁT AN NINH MẠNG</div>
      <nav className="side-nav" aria-label="Điều hướng chính">{links.filter(link => link.href !== "/admin" || role === "admin").map(link =>
        <Link key={link.href} href={link.href} aria-current={pathname === link.href ? "page" : undefined} className={`nav-link${pathname === link.href ? " active" : ""}`}>
          {link.label}</Link>)}</nav>
      <div className="sidebar-source"><span className="minor-label">NGUỒN DỮ LIỆU</span><strong>Cloudflare Radar · Việt Nam</strong><small>Chỉ số chuẩn hóa / tỉ lệ %</small></div>
      <div className="sidebar-user"><strong>{role === "viewer" ? "Nguyễn Văn A" : "Nguyễn Văn B"} · {role === "viewer" ? "Viewer" : "Admin"}</strong><small>Vai trò xem thử · chưa đăng nhập</small></div>
    </aside>
    <div className="main-column"><header className="topbar"><div className="breadcrumbs"><b>RADAR / VN</b> / {links.find(link => link.href === pathname)?.label ?? "Dashboard"}</div>
      <div className="top-actions"><span className="mode-badge">{DATA_MODE === "demo" ? "MÔ PHỎNG · 8 GIÂY" : "CHẾ ĐỘ API"}</span>
        <label className="screen-reader-only" htmlFor="role-preview">Vai trò xem thử</label>
        <select id="role-preview" className="role-select" value={role} onChange={e => changeRole(e.target.value as Role)}>
          <option value="viewer">Nguyễn Văn A · Viewer</option><option value="admin">Nguyễn Văn B · Admin</option></select></div></header>
      <main className="content">{children}</main></div>
  </div></RoleContext.Provider>;
}
