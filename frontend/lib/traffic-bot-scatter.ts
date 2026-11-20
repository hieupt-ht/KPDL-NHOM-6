import type { ClusterResult, TimeseriesPoint } from "../types/api";
import { ApiError } from "./api-core";
import { vietnamDay } from "./date-utils";

type Query<T> = { data?: T[]; isLoading?: boolean; error?: Error };
type Measurement = Pick<TimeseriesPoint, "ts" | "mean">;
type Label = Pick<ClusterResult, "date" | "cluster_name">;
const names = ["Bình thường", "Cao điểm", "Bất thường", "Chưa phân cụm", "Nhãn chưa hỗ trợ"] as const;
const recognizedLabels = new Set<string>(names.slice(0, 3));

/** HTTP/Bot are required; cluster labels only enrich the already available points. */
export function trafficBotScatter(http: Query<Measurement>, bot: Query<Measurement>, clusters: Query<Label>) {
  const labels = new Map(!clusters.error && !clusters.isLoading ? clusters.data?.map(row => [row.date, row.cluster_name]) : []);
  const botByTime = new Map(bot.data?.map(row => [Date.parse(row.ts), row.mean]));
  const grouped = new Map<string, [number, number][]>(names.map(name => [name, []]));
  for (const row of http.data ?? []) {
    const instant = Date.parse(row.ts);
    const y = botByTime.get(instant);
    if (!Number.isFinite(instant) || row.mean == null || !Number.isFinite(row.mean) || y == null || !Number.isFinite(y)) continue;
    const label = labels.get(vietnamDay(row.ts));
    const group = label == null ? "Chưa phân cụm" : recognizedLabels.has(label) ? label : "Nhãn chưa hỗ trợ";
    grouped.get(group)!.push([row.mean, y]);
  }
  const groups = [...grouped].map(([name, data]) => ({ name, data })).filter(group => group.data.length > 0);
  const pointCount = groups.reduce((sum, group) => sum + group.data.length, 0);
  const clusterStatus = clusters.isLoading ? "loading" : clusters.error ?
    clusters.error instanceof ApiError && clusters.error.status === 404 ? "missing" : "unavailable" :
    clusters.data?.length ? "available" : "missing";
  return {
    groups, pointCount, clusterStatus,
    loading: Boolean(http.isLoading || bot.isLoading),
    error: http.error || bot.error,
    empty: pointCount === 0,
  };
}
