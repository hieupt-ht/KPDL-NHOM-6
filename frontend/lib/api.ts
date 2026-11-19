import { getSession } from "next-auth/react";
import type { Session } from "next-auth";
import type { AcceptedJob, ClusterResult, CorrelationPoint, DateRange, ForecastContinuous, ForecastDiscrete, HistogramBin, Metric, SeasonalPoint, ServiceRun, StatusResponse, TimeseriesPoint, TrendPoint } from "@/types/api";
import * as demo from "@/lib/demo-data";
import { ApiError, createApiTransport } from "./api-core";

export { ApiError } from "./api-core";
export const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
export const DATA_MODE = process.env.NEXT_PUBLIC_DATA_MODE === "api" ? "api" : "demo";
export const DATA_REFRESH_INTERVAL = DATA_MODE === "demo" ? 8_000 : 300_000;
let sessionRequest: Promise<Session | null> | undefined;

export function clearAuthCache() { sessionRequest = undefined; }
export async function getAccessToken(): Promise<string | null> {
  if (!sessionRequest) {
    const pending = getSession();
    sessionRequest = pending;
    void pending.finally(() => { if (sessionRequest === pending) sessionRequest = undefined; }).catch(() => {});
  }
  const session = await sessionRequest;
  return session?.error ? null : session?.accessToken ?? null;
}
const api = createApiTransport({ baseUrl: API_BASE_URL, getToken: getAccessToken });

export function getTimeseries(q: DateRange & { granularity: "day" | "week" | "month"; metric: Metric }): Promise<TimeseriesPoint[]> {
  return DATA_MODE === "demo" ? Promise.resolve(demo.timeseries(q)) : api.list("timeseries", { ...api.range(q), metric: q.metric, granularity: q.granularity });
}
export function getHistogram(q: DateRange & { metric: Metric }): Promise<HistogramBin[]> {
  return DATA_MODE === "demo" ? Promise.resolve(demo.histogram(q.metric, q)) : api.request("histogram", { metric: q.metric });
}
export function getTrend(q: DateRange & { granularity: "month" | "week"; metric: Metric }): Promise<TrendPoint[]> {
  return DATA_MODE === "demo" ? Promise.resolve(demo.trend(q)) : api.request("trend", { ...api.range(q), metric: q.metric, granularity: q.granularity });
}
export function getSeasonal(q: DateRange & { period_type: "hour_of_day" | "day_of_week" | "month"; metric: Metric }): Promise<SeasonalPoint[]> {
  return DATA_MODE === "demo" ? Promise.resolve(demo.seasonal(q)) : api.request("seasonal", { period_type: q.period_type, metric: q.metric });
}
export function getCorrelation(q: DateRange = {}): Promise<CorrelationPoint[]> {
  return DATA_MODE === "demo" ? Promise.resolve(demo.correlation(q)) : api.request("correlation");
}
export function getClusters(q: DateRange = {}): Promise<ClusterResult[]> {
  return DATA_MODE === "demo" ? Promise.resolve(demo.clusters(q)) : api.list("clusters", api.range(q));
}
export function getForecastContinuous(q: DateRange = {}): Promise<ForecastContinuous> {
  return DATA_MODE === "demo" ? Promise.resolve(demo.forecastContinuous()) : api.request("forecast/continuous", api.range(q));
}
export function getForecastDiscrete(q: DateRange = {}): Promise<ForecastDiscrete> {
  return DATA_MODE === "demo" ? Promise.resolve(demo.forecastDiscrete()) : api.request("forecast/discrete", api.range(q));
}
export function getStatus(): Promise<StatusResponse> {
  return DATA_MODE === "demo" ? Promise.resolve(demo.status()) : api.request("status");
}
export async function runJob(service: "analysis" | "clustering" | "prediction"): Promise<AcceptedJob> {
  if (DATA_MODE === "demo") throw new ApiError(400, "Chế độ minh họa không chạy job thật.");
  return api.request(`jobs/${service}/run`, undefined, { method: "POST" });
}
export function getJobRun(id: number): Promise<ServiceRun> {
  return api.request(`jobs/runs/${id}`);
}
