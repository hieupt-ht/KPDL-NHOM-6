import type { Metadata, Viewport } from "next";
import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import AppShell from "@/components/layout/AppShell";
import "./globals.css";

export const metadata: Metadata = { title: "Cyber Radar VN", description: "Dashboard giám sát an ninh mạng Việt Nam" };
export const viewport: Viewport = { themeColor: [{ media: "(prefers-color-scheme: light)", color: "#F4F7FB" }, { media: "(prefers-color-scheme: dark)", color: "#070D1A" }] };

// Đặt theme trước khi React hydrate để tránh nháy màu khi tải trang.
const themeScript = `try{var t=localStorage.getItem("radar-theme");if(t!=="light"&&t!=="dark")t=matchMedia("(prefers-color-scheme: dark)").matches?"dark":"light";document.documentElement.dataset.theme=t}catch(e){document.documentElement.dataset.theme="light"}`;

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="vi" suppressHydrationWarning><head><script dangerouslySetInnerHTML={{ __html: themeScript }} /></head><body><AppShell>{children}</AppShell></body></html>;
}
