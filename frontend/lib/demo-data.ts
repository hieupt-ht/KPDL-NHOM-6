import type {
  ClusterResult, CorrelationPoint, DateRange, ForecastContinuous, ForecastDiscrete,
  HistogramBin, Metric, SeasonalPoint, StatusResponse, TimeseriesPoint, TrendPoint,
} from "@/types/api";

const anchor = Date.UTC(2026, 10, 17);
const day = 86_400_000;
const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value));
const round = (value: number) => Math.round(value * 1000) / 1000;
const stamp = (i: number) => new Date(anchor + i * day).toISOString();

function value(metric: Metric, i: number): number {
  const wave = Math.sin(i * .18) * .13 + Math.cos(i * .47) * .045;
  const spike = i > -11 && i < -6 ? .26 : 0;
  // Only the last demo sample changes. Earlier observations and their timestamps stay fixed.
  // A shared time step keeps HTTP, L7, bot, clusters and derived charts in sync.
  const phase = Math.floor(Date.now() / 8_000) * .55;
  const recent = i === 0 ? Math.sin(phase) : 0;
  switch (metric) {
    case "http_traffic": return round(clamp(.62 + wave + i * .0006 + recent * .045, .08, .96));
    case "l7_attack": return round(clamp(.18 + Math.sin(i * .28) * .065 + spike + recent * .03, .02, .85));
    case "bot_share": return round(clamp(32 + Math.sin(i * .21) * 8 + spike * 35 + recent * 2.2, 5, 75));
    case "human_share": return round(100 - value("bot_share", i));
    case "netflows": return round(clamp(.55 + wave * .72 + recent * .035, .05, .95));
  }
}

function inRange(iso: string, q: DateRange) {
  return (!q.start || iso >= q.start) && (!q.end || iso.slice(0, 10) <= q.end.slice(0, 10));
}

export function timeseries(q: DateRange & { granularity: "day" | "week" | "month"; metric: Metric }): TimeseriesPoint[] {
  const step = q.granularity === "day" ? 1 : q.granularity === "week" ? 7 : 30;
  const points: TimeseriesPoint[] = [];
  for (let i = -89; i <= 0; i += step) {
    const samples = Array.from({ length: step }, (_, j) => value(q.metric, Math.min(0, i + j)));
    const ts = stamp(i);
    if (inRange(ts, q)) points.push({ granularity: q.granularity, ts, metric: q.metric,
      mean: round(samples.reduce((a, b) => a + b, 0) / samples.length), min: Math.min(...samples), max: Math.max(...samples) });
  }
  return points;
}

export function histogram(metric: Metric, q: DateRange): HistogramBin[] {
  const max = metric.endsWith("share") ? 100 : 1;
  const values = Array.from({ length: 90 }, (_, j) => j - 89).filter(i => inRange(stamp(i), q)).map(i => value(metric, i));
  return Array.from({ length: 20 }, (_, i) => ({ metric, bin_start: i * max / 20,
    bin_end: (i + 1) * max / 20, count: values.filter(v => v >= i * max / 20 && (i === 19 ? v <= max : v < (i + 1) * max / 20)).length }));
}

export function trend(q: DateRange & { granularity: "month" | "week"; metric: Metric }): TrendPoint[] {
  return timeseries(q).map((point, i, all) => ({ granularity: q.granularity, ts: point.ts, metric: q.metric,
    trend_value: round(all.slice(Math.max(0, i - 2), i + 1).reduce((sum, p) => sum + p.mean!, 0) / Math.min(3, i + 1)) }));
}

export function seasonal(q: { period_type: "hour_of_day" | "day_of_week" | "month"; metric: Metric }): SeasonalPoint[] {
  const count = q.period_type === "hour_of_day" ? 24 : q.period_type === "day_of_week" ? 7 : 12;
  return Array.from({ length: count }, (_, bucket) => ({ metric: q.metric, period_type: q.period_type, bucket: q.period_type === "month" ? bucket + 1 : bucket,
    value: round(clamp(value(q.metric, -bucket) + Math.sin(bucket * .51 - 1.4) * (q.metric.endsWith("share") ? 4 : .075), 0, q.metric.endsWith("share") ? 100 : 1)) }));
}

const metrics: Metric[] = ["http_traffic", "l7_attack", "bot_share", "human_share", "netflows"];
export function correlation(q: DateRange): CorrelationPoint[] {
  const indices = Array.from({ length: 90 }, (_, j) => j - 89).filter(i => inRange(stamp(i), q));
  function pearson(a: Metric, b: Metric) {
    if (a === b) return 1;
    if (indices.length < 2) return 0;
    const xs = indices.map(i => value(a, i)), ys = indices.map(i => value(b, i));
    const mx = xs.reduce((sum, x) => sum + x, 0) / xs.length;
    const my = ys.reduce((sum, y) => sum + y, 0) / ys.length;
    const numerator = xs.reduce((sum, x, i) => sum + (x - mx) * (ys[i] - my), 0);
    const dx = xs.reduce((sum, x) => sum + (x - mx) ** 2, 0);
    const dy = ys.reduce((sum, y) => sum + (y - my) ** 2, 0);
    return dx && dy ? round(numerator / Math.sqrt(dx * dy)) : 0;
  }
  return metrics.flatMap(var_x => metrics.map(var_y => ({ var_x, var_y, coef: pearson(var_x, var_y), computed_at: stamp(0) })));
}

export function clusters(q: DateRange): ClusterResult[] {
  return Array.from({ length: 90 }, (_, j) => {
    const i = j - 89, attack = value("l7_attack", i), traffic = value("http_traffic", i);
    const cluster_id = attack > .32 ? 2 : traffic > .73 ? 1 : 0;
    return { date: stamp(i).slice(0, 10), cluster_id,
      cluster_name: ["Bình thường", "Cao điểm", "Bất thường"][cluster_id],
      features: { http_mean: traffic, l7_max: attack, bot_mean: value("bot_share", i) }, computed_at: stamp(i) };
  }).filter(row => inRange(row.date, q));
}

export function forecastContinuous(): ForecastContinuous {
  return { target_date: "2026-11-18", predicted_value: .71, model_name: "Random Forest Regressor", created_at: stamp(0) };
}
export function forecastDiscrete(): ForecastDiscrete {
  return { target_date: "2026-11-18", label: "Cao", probability: .76, model_name: "Random Forest Classifier", created_at: stamp(0) };
}
export function status(): StatusResponse {
  return { data_freshness: { id: 1, latest_silver_ts: stamp(0), computed_at: stamp(0) },
    service_runs: [
      { id: 3, service: "analysis", started_at: stamp(0), finished_at: stamp(0), status: "success", error: null },
      { id: 2, service: "prediction", started_at: stamp(0), finished_at: stamp(0), status: "success", error: null },
      { id: 1, service: "clustering", started_at: stamp(-1), finished_at: stamp(-1), status: "success", error: null },
    ] };
}
