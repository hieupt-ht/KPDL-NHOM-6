import Link from "next/link";

export default function AdminPage() {
  return <main className="mx-auto max-w-5xl space-y-8 px-4 py-8"><Link href="/" className="text-cyan-700 underline dark:text-cyan-300">← Dashboard</Link><div><h1 className="text-3xl font-bold">Quản trị công việc</h1><p className="mt-2 text-slate-500">Các nút chạy sẽ được kết nối API ở giai đoạn sau.</p></div><section className="grid gap-4 sm:grid-cols-3">{["Analysis", "Clustering", "Prediction"].map(name => <article key={name} className="rounded-2xl border bg-white p-5 dark:border-slate-700 dark:bg-slate-900"><h2 className="mb-4 font-semibold">{name}</h2><button type="button" className="rounded-lg bg-cyan-700 px-4 py-2 text-white">Run</button></article>)}</section><section className="rounded-2xl border bg-white p-5 dark:border-slate-700 dark:bg-slate-900"><h2 className="font-semibold">Lịch sử service_runs</h2><p className="mt-6 text-sm text-slate-500">Chưa có dữ liệu</p></section></main>;
}
