import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = { title: "Cyber Radar VN", description: "Dashboard giám sát an ninh mạng Việt Nam" };

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="vi"><body className="min-h-screen bg-slate-100 text-slate-900 dark:bg-slate-950 dark:text-slate-100">{children}</body></html>;
}
