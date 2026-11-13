export default function KpiCard({ title }: { title: string }) {
  return <article className="rounded-2xl border border-slate-200 bg-white p-5 dark:border-slate-700 dark:bg-slate-900">
    <h2 className="text-sm text-slate-500 dark:text-slate-400">{title}</h2>
    <p className="mt-5 text-lg font-semibold">Chưa có dữ liệu</p>
  </article>;
}
