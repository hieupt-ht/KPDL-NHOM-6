"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { SessionProvider, signIn, signOut, useSession } from "next-auth/react";
import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { SWRConfig } from "swr";
import { ApiError, clearAuthCache, DATA_MODE } from "@/lib/api";

type Role = "viewer" | "admin";
const RoleContext = createContext<{ role: Role; isDemo: boolean }>({ role: "viewer", isDemo: true });
export const useDashboardRole = () => useContext(RoleContext);
const links = [
  { href: "/", label: "Tổng quan" },
  { href: "/analysis", label: "Phân tích dữ liệu" },
  { href: "/forecast", label: "Dự báo & phân cụm" },
  { href: "/admin", label: "Vận hành hệ thống" },
];

function Shell({ children, role, name, preview, setRole, onLogout, busy = false }: {
  children: ReactNode; role: Role; name: string; preview: boolean;
  setRole?: (role: Role) => void; onLogout?: () => void; busy?: boolean;
}) {
  const pathname = usePathname();
  return <RoleContext.Provider value={{ role, isDemo: preview }}><div className="shell">
    <aside className="sidebar">
      <Link href="/" className="brand"><span className="brand-mark">R</span><span>RADAR / VN</span></Link>
      <div className="sidebar-caption">GIÁM SÁT AN NINH MẠNG</div>
      <nav className="side-nav" aria-label="Điều hướng chính">{links.filter(link => link.href !== "/admin" || role === "admin").map(link =>
        <Link key={link.href} href={link.href} aria-current={pathname === link.href ? "page" : undefined} className={`nav-link${pathname === link.href ? " active" : ""}`}>{link.label}</Link>)}</nav>
      <div className="sidebar-source"><span className="minor-label">NGUỒN DỮ LIỆU</span><strong>Cloudflare Radar · Việt Nam</strong><small>Chỉ số tương đối / tỉ lệ %</small></div>
      <div className="sidebar-user"><strong>{name} · {role === "viewer" ? "Viewer" : "Admin"}</strong><small>{preview ? "Vai trò xem thử · chưa đăng nhập" : "Đã xác thực qua Keycloak"}</small></div>
    </aside>
    <div className="main-column"><header className="topbar"><div className="breadcrumbs"><b>RADAR / VN</b> / {links.find(link => link.href === pathname)?.label ?? "Dashboard"}</div>
      <div className="top-actions"><span className="mode-badge">{preview ? "MÔ PHỎNG · 8 GIÂY" : "API · ĐÃ ĐĂNG NHẬP"}</span>
        {preview ? <><label className="screen-reader-only" htmlFor="role-preview">Vai trò xem thử</label><select id="role-preview" className="role-select" value={role} onChange={e => setRole?.(e.target.value as Role)}>
          <option value="viewer">Nguyễn Văn A · Viewer</option><option value="admin">Nguyễn Văn B · Admin</option></select></> :
          <button type="button" className="button" disabled={busy} onClick={onLogout}>{busy ? "Đang đăng xuất…" : "Đăng xuất"}</button>}
      </div></header><main className="content">{children}</main></div>
  </div></RoleContext.Provider>;
}

function DemoShell({ children }: { children: ReactNode }) {
  const [role, setRole] = useState<Role>("viewer");
  return <Shell role={role} name={role === "admin" ? "Nguyễn Văn B" : "Nguyễn Văn A"} preview setRole={setRole}>{children}</Shell>;
}

function LiveShell({ children }: { children: ReactNode }) {
  const { data: session, status } = useSession();
  const pathname = usePathname();
  const [busy, setBusy] = useState(false);
  const [authRejected, setAuthRejected] = useState(false);
  const [logoutError, setLogoutError] = useState<string | null>(null);
  useEffect(() => {
    const reject = () => setAuthRejected(true);
    window.addEventListener("radar:unauthorized", reject);
    return () => window.removeEventListener("radar:unauthorized", reject);
  }, []);
  if (status === "loading") return <div className="access-state panel" role="status"><h1>Đang kiểm tra phiên đăng nhập…</h1></div>;
  if (!session?.accessToken || session.error || authRejected) return <div className="access-state panel">
    <span className="eyebrow">RADAR / VN · Keycloak</span><h1>Đăng nhập để xem dữ liệu</h1>
    <p className="lead">Dùng tài khoản Viewer để xem dashboard hoặc Admin để vận hành tác vụ.</p>
    {(session?.error || authRejected) && <p role="alert">Phiên đăng nhập đã hết hạn hoặc không còn hợp lệ. Vui lòng đăng nhập lại.</p>}
    <button className="button primary" onClick={() => { clearAuthCache(); void signIn("keycloak", { callbackUrl: pathname }); }}>Đăng nhập Keycloak</button>
  </div>;
  const role = session.roles.includes("admin") ? "admin" : "viewer";
  async function logout() {
    setBusy(true); setLogoutError(null);
    try {
      const response = await fetch("/api/logout-url", { method: "POST", cache: "no-store" });
      if (!response.ok) throw new Error("LogoutFailed");
      const { url } = await response.json();
      clearAuthCache();
      await signOut({ redirect: false });
      window.location.assign(url);
    } catch { setBusy(false); setLogoutError("Chưa hoàn tất đăng xuất. Vui lòng thử lại."); }
  }
  return <SWRConfig key={session.user.id} value={{
    provider: () => new Map(),
    shouldRetryOnError: error => !(error instanceof ApiError && [401, 403, 404, 422].includes(error.status)),
    errorRetryCount: 2,
    onError: error => { if (error instanceof ApiError && error.status === 401) window.dispatchEvent(new Event("radar:unauthorized")); },
  }}><Shell role={role} name={session.user.name || "Tài khoản"} preview={false} onLogout={() => void logout()} busy={busy}>
    {logoutError && <p className="notice" role="alert">{logoutError}</p>}{children}
  </Shell></SWRConfig>;
}

export default function AppShell({ children }: { children: ReactNode }) {
  return DATA_MODE === "demo" ? <DemoShell>{children}</DemoShell> :
    <SessionProvider refetchInterval={60} refetchOnWindowFocus><LiveShell>{children}</LiveShell></SessionProvider>;
}
