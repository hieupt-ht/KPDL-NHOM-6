import Link from "next/link";
import BotScatterChart from "@/components/charts/BotScatterChart";
import ClusterChart from "@/components/charts/ClusterChart";
import CorrelationHeatmap from "@/components/charts/CorrelationHeatmap";
import ForecastCard from "@/components/charts/ForecastCard";
import Histogram from "@/components/charts/Histogram";
import RiskLabel from "@/components/charts/RiskLabel";
import SeasonalChart from "@/components/charts/SeasonalChart";
import TrafficLineChart from "@/components/charts/TrafficLineChart";
import TrendChart from "@/components/charts/TrendChart";
import GranularityTabs from "@/components/filters/GranularityTabs";
import TimeRangeFilter from "@/components/filters/TimeRangeFilter";
import KpiCard from "@/components/kpi/KpiCard";

const kpis = ["Dự báo lưu lượng ngày mai", "Rủi ro ngày mai", "Cụm hôm nay", "Tỉ lệ bot hiện tại"];

export default function Home() {
  return <main className="mx-auto max-w-7xl space-y-8 px-4 py-8 sm:px-6">
    <header className="flex flex-wrap items-center justify-between gap-4">
      <div><p className="text-xs font-semibold uppercase tracking-widest text-cyan-700 dark:text-cyan-300">Cyber Radar VN</p><h1 className="text-3xl font-bold">Tổng quan an ninh mạng Việt Nam</h1><p className="mt-1 text-sm text-slate-500">Cập nhật lúc: Chưa có dữ liệu · Người dùng: demo</p></div>
      <nav className="flex items-center gap-4 text-sm"><Link href="/admin" className="text-cyan-700 underline dark:text-cyan-300">Quản trị</Link><button type="button" className="rounded-lg border px-3 py-2">Đăng xuất</button></nav>
    </header>
    <div className="flex flex-wrap gap-3"><TimeRangeFilter /><GranularityTabs /><div className="rounded-lg border border-slate-300 px-3 py-2 text-sm dark:border-slate-600">Chỉ số · Chưa chọn</div></div>
    <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4" aria-label="Chỉ số tổng quan">{kpis.map(title => <KpiCard key={title} title={title} />)}</section>
    <section className="grid gap-5 md:grid-cols-2" aria-label="Biểu đồ placeholder"><TrafficLineChart /><BotScatterChart /><Histogram /><TrendChart /><SeasonalChart /><CorrelationHeatmap /><ForecastCard /><RiskLabel /><ClusterChart /></section>
  </main>;
}
