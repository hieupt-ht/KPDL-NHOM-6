import type { ReactNode } from "react";

export default function ChartCard({ title, children }: { title: string; children?: ReactNode }) {
  return <section className="rounded-2xl border border-slate-200 bg-white p-5 shadow-sm dark:border-slate-700 dark:bg-slate-900">
    <h2 className="mb-4 text-base font-semibold">{title}</h2>
    {children ?? <div className="flex h-48 items-center justify-center rounded-xl bg-slate-100 text-sm text-slate-500 dark:bg-slate-800 dark:text-slate-400">Chưa có dữ liệu</div>}
  </section>;
}
