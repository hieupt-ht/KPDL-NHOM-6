import type { TimeseriesPoint, TrendPoint } from "../types/api";

/** Decomposition trims edge buckets; series must join by instant, never array index. */
export function alignTrendSeries(means: Pick<TimeseriesPoint, "ts" | "mean">[] = [], trends: Pick<TrendPoint, "ts" | "trend_value">[] = []) {
  const meanByTime = new Map(means.map(row => [Date.parse(row.ts), row.mean]));
  const trendByTime = new Map(trends.map(row => [Date.parse(row.ts), row.trend_value]));
  const times = [...new Set([...meanByTime.keys(), ...trendByTime.keys()])].sort((a, b) => a - b);
  return {
    timestamps: times.map(time => new Date(time).toISOString()),
    means: times.map(time => meanByTime.get(time) ?? null),
    trends: times.map(time => trendByTime.get(time) ?? null),
  };
}

// Current Analysis coverage; do not fabricate distributions for other metrics.
export const analysisHistogramMetrics = new Set(["http_traffic", "l7_attack", "bot_share"]);
