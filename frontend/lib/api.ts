import type {
  ClusterResult, CorrelationPoint, DateRange, ForecastContinuous, ForecastDiscrete,
  HistogramBin, Metric, SeasonalPoint, StatusResponse, TimeseriesPoint, TrendPoint,
} from "@/types/api";
import * as demo from "@/lib/demo-data";

export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
export const DATA_MODE = process.env.NEXT_PUBLIC_DATA_MODE === "api" ? "api" : "demo";
// Demo revalidates often to show one changing sample; production checks the API every five minutes.
export const DATA_REFRESH_INTERVAL = DATA_MODE === "demo" ? 8_000 : 300_000;

// Replace with the Keycloak access token from Auth.js when SSO is integrated.
// The role preview switch in the UI is not authentication.
export function getAccessToken(): string | null { return null; }

function url(path: string, query: Record<string, string | undefined> = {}) {
  const u = new URL(`/api/${path}`, API_BASE_URL);
  Object.entries(query).forEach(([key, value]) => { if (value) u.searchParams.set(key, value); });
  return u.toString();
}

async function request<T>(path: string, query?: Record<string, string | undefined>, init?: RequestInit): Promise<T> {
  const token = getAccessToken();
  const response = await fetch(url(path, query), {
    ...init,
    headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), ...init?.headers },
  });
  if (!response.ok) {
    const message = response.status === 501 ? "API này đang được nhóm backend hoàn thiện." :
      response.status === 404 ? "Data Mart chưa có dữ liệu cho lựa chọn này." :
      response.status === 401 || response.status === 403 ? "Bạn chưa có quyền truy cập dữ liệu này." :
      `Không tải được dữ liệu (HTTP ${response.status}).`;
    throw new Error(message);
  }
  const body = await response.text();
  return (body ? JSON.parse(body) : undefined) as T;
}

export function getTimeseries(q: DateRange & { granularity: "day" | "week" | "month"; metric: Metric }): Promise<TimeseriesPoint[]> {
  return DATA_MODE === "demo" ? Promise.resolve(demo.timeseries(q)) : request("timeseries", q);
}
export function getHistogram(q: DateRange & { metric: Metric }): Promise<HistogramBin[]> {
  return DATA_MODE === "demo" ? Promise.resolve(demo.histogram(q.metric, q)) : request("histogram", q);
}
export function getTrend(q: DateRange & { granularity: "month" | "week"; metric: Metric }): Promise<TrendPoint[]> {
  return DATA_MODE === "demo" ? Promise.resolve(demo.trend(q)) : request("trend", q);
}
export function getSeasonal(q: DateRange & { period_type: "hour_of_day" | "day_of_week" | "month"; metric: Metric }): Promise<SeasonalPoint[]> {
  return DATA_MODE === "demo" ? Promise.resolve(demo.seasonal(q)) : request("seasonal", q);
}
export function getCorrelation(q: DateRange = {}): Promise<CorrelationPoint[]> {
  return DATA_MODE === "demo" ? Promise.resolve(demo.correlation(q)) : request("correlation", q);
}
export function getClusters(q: DateRange = {}): Promise<ClusterResult[]> {
  return DATA_MODE === "demo" ? Promise.resolve(demo.clusters(q)) : request("clusters", q);
}
export function getForecastContinuous(q: DateRange = {}): Promise<ForecastContinuous> {
  return DATA_MODE === "demo" ? Promise.resolve(demo.forecastContinuous()) : request("forecast/continuous", q);
}
export function getForecastDiscrete(q: DateRange = {}): Promise<ForecastDiscrete> {
  return DATA_MODE === "demo" ? Promise.resolve(demo.forecastDiscrete()) : request("forecast/discrete", q);
}
export function getStatus(q: DateRange = {}): Promise<StatusResponse> {
  return DATA_MODE === "demo" ? Promise.resolve(demo.status()) : request("status", q);
}
export async function runJob(service: "analysis" | "clustering" | "prediction"): Promise<void> {
  if (DATA_MODE === "demo") throw new Error("Chế độ minh họa không chạy job thật.");
  await request<unknown>(`jobs/${service}/run`, undefined, { method: "POST" });
}
